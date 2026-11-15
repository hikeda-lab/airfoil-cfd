"""保存レベル（minimal / standard / full）に従ってアーカイブ対象ファイルを選ぶ。読み取り専用。

ケース内の全ファイルをカテゴリ分けし、選択／非選択を決める。非選択分の集計は
「アーカイブ後に削除候補になり得る量」の目安にもなる（実際の削除判断は prune-plan で別途）。
"""
from __future__ import annotations

import fnmatch
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from airfoil_cfd.datamgmt import meta as M
from airfoil_cfd.datamgmt.config import Config, Tier

REPO_PREFIX = "_repo"   # ケース外（repo 相対）のファイルはアーカイブ内で _repo/<path> に置く


def glob_to_regex(pat: str) -> re.Pattern:
    """`**` は "/" を跨ぐ、`*` は跨がない。末尾 `/**` はディレクトリ自身の配下全部。"""
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += r"(?:.*/)?"; i += 3
        elif pat.startswith("**", i):
            out += r".*"; i += 2
        elif pat[i] == "*":
            out += r"[^/]*"; i += 1
        elif pat[i] == "?":
            out += r"[^/]"; i += 1
        else:
            out += re.escape(pat[i]); i += 1
    return re.compile(rf"^{out}$")


def _matches(rel: str, regs: list[re.Pattern]) -> bool:
    return any(r.match(rel) for r in regs)


@dataclass
class Options:
    """LES 等の選択オプション（CLI から渡す）。"""
    snapshots: list[str] | None = None   # 明示指定の瞬時場時刻。None なら tier の les_snapshots で自動選択
    n_snapshots: int | None = None       # 自動選択の個数を上書き（0 で無し）
    mean: bool = True                    # *Mean を含める
    rms: bool = True                     # *Prime2Mean を含める
    acoustic_series: bool = False        # surfaces/probes/forceCoeffs の全時系列を含める
    include_vtk: bool = False            # VTK/ を含める（full のみ有効）


@dataclass
class Entry:
    src: str          # 絶対パス
    arc: str          # アーカイブ内の相対パス（data/ 以下）
    size: int
    category: str


@dataclass
class Selection:
    tier: str
    case: str
    selected: list[Entry] = field(default_factory=list)
    skipped: list[Entry] = field(default_factory=list)
    snapshot_times: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def selected_bytes(self) -> int:
        return sum(e.size for e in self.selected)

    @property
    def skipped_bytes(self) -> int:
        return sum(e.size for e in self.skipped)

    def by_category(self) -> dict[str, list[int]]:
        """category -> [selected_bytes, selected_files, skipped_bytes, skipped_files]"""
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        for e in self.selected:
            agg[e.category][0] += e.size; agg[e.category][1] += 1
        for e in self.skipped:
            agg[e.category][2] += e.size; agg[e.category][3] += 1
        return dict(sorted(agg.items()))


def _auto_snapshots(times: list[str], n: int) -> list[str]:
    """後半（発達後）から等間隔に n 個。最終時刻は latest で別途入るので除く。"""
    cand = [t for t in times if t != "0"]
    if n <= 0 or len(cand) < 2:
        return []
    cand = cand[:-1]
    t_end = float(cand[-1])
    t0 = float(cand[0]) + 0.5 * (t_end - float(cand[0]))
    late = [t for t in cand if float(t) >= t0] or cand
    if len(late) <= n:
        return late
    step = (len(late) - 1) / (n - 1) if n > 1 else 0
    idx = sorted({round(i * step) for i in range(n)}) if n > 1 else [len(late) - 1]
    return [late[i] for i in idx]


def _field_kind(name: str, les_fields: dict) -> str:
    if any(fnmatch.fnmatch(name, p) for p in les_fields.get("rms", [])):
        return "rms"
    if any(fnmatch.fnmatch(name, p) for p in les_fields.get("mean", [])):
        return "mean"
    return "field"


def select(case: str, meta: dict, tier: Tier, cfg: Config, opts: Options | None = None,
           repo: str | None = None) -> Selection:
    opts = opts or Options()
    repo = repo or cfg.repo
    case = os.path.abspath(case)
    sel = Selection(tier=tier.name, case=case)
    inc = [glob_to_regex(p) for p in tier.include]
    exc = [glob_to_regex(p) for p in cfg.global_exclude]
    les = M.is_les(meta)

    # ---- 時刻ディレクトリの選択 --------------------------------------------
    times = M.time_dirs(case)
    keep_times: set[str] = set()
    if "all" in tier.time_dirs:
        keep_times |= set(times)
    if "latest" in tier.time_dirs and times:
        keep_times.add(times[-1])
    if tier.time_dirs:   # standard 以上で LES 瞬時場
        if opts.snapshots is not None:
            snaps = [t for t in opts.snapshots if t in times]
            for t in set(opts.snapshots) - set(times):
                sel.warnings.append(f"指定時刻 {t} の時刻ディレクトリがありません")
        elif les:
            n = tier.les_snapshots if opts.n_snapshots is None else opts.n_snapshots
            snaps = _auto_snapshots(times, n)
        else:
            snaps = []
        keep_times |= set(snaps)
        sel.snapshot_times = sorted(set(snaps), key=float)
    if les and tier.time_dirs and not meta.get("outputs", {}).get("has_mean"):
        sel.warnings.append("LES ですが最終時刻に *Mean/*Prime2Mean がありません（fieldAverage 未設定）")

    # ---- processor* の扱い --------------------------------------------------
    rs = M.reconstruct_status(case)
    proc_times: set[str] | None = None   # None=全部除外, set=その時刻 + constant だけ含める
    if tier.processor == "always":
        proc_times = {"*"}
    elif tier.processor == "if_not_reconstructed" and not rs["reconstructed"]:
        proc_times = set(rs["missing_times"]) if "all" in tier.time_dirs else (
            set(rs["missing_times"]) & keep_times)
        if proc_times:
            sel.warnings.append(
                f"未 reconstruct の時刻 {len(proc_times)} 個は processor* から保存します"
                f"（{min(proc_times, key=float)}〜{max(proc_times, key=float)}）")
    elif not rs["reconstructed"] and tier.processor != "always":
        sel.warnings.append(
            f"未 reconstruct の時刻 {len(rs['missing_times'])} 個は processor* にのみ存在し、"
            f"この保存レベルには含まれません")

    surf_all = tier.surfaces == "all" or opts.acoustic_series
    surf_latest = tier.surfaces == "latest"

    # ---- ケース内の全ファイルを走査 -----------------------------------------
    for dirpath, dirnames, filenames in os.walk(case):
        dirnames.sort()
        for fn in sorted(filenames):
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, case).replace(os.sep, "/")
            try:
                size = os.lstat(src).st_size
            except OSError:
                continue
            cat, take = _classify(rel, fn, size, tier, inc, exc, keep_times, proc_times,
                                  surf_all, surf_latest, opts, cfg, case)
            e = Entry(src=src, arc=rel, size=size, category=cat)
            (sel.selected if take else sel.skipped).append(e)
    for nested in sorted({e.category.split(":", 1)[1] for e in sel.skipped
                          if e.category.startswith("nested-case:")}):
        sel.warnings.append(f"入れ子のケース {nested}/ は含めません（別 run として登録してください）")

    # ---- ケース外: 図・extra_paths ------------------------------------------
    if tier.include_figures:
        for src in _figure_files(cfg, meta, repo):
            rel = os.path.relpath(src, repo).replace(os.sep, "/")
            sel.selected.append(Entry(src, f"{REPO_PREFIX}/{rel}", os.path.getsize(src), "figures"))
    order = list(cfg.tiers)
    for ep in meta.get("extra_paths") or []:
        path, ep_tier = (ep, "full") if isinstance(ep, str) else (ep["path"], ep.get("tier", "full"))
        want = order.index(tier.name) >= order.index(ep_tier) if ep_tier in order else False
        absp = os.path.join(repo, path)
        files = [absp] if os.path.isfile(absp) else [
            os.path.join(d, f) for d, _, fs in os.walk(absp) for f in fs]
        if not files:
            sel.warnings.append(f"extra_paths が見つかりません: {path}")
        for src in sorted(files):
            rel = os.path.relpath(src, repo).replace(os.sep, "/")
            e = Entry(src, f"{REPO_PREFIX}/{rel}", os.path.getsize(src), f"extra:{path}")
            (sel.selected if want else sel.skipped).append(e)
    return sel


def _classify(rel, fn, size, tier, inc, exc, keep_times, proc_times, surf_all, surf_latest,
              opts, cfg, case) -> tuple[str, bool]:
    parts = rel.split("/")
    top = parts[0]
    if _matches(rel, exc) or fn == ".DS_Store":
        return "excluded", False
    # #calc 等のコンパイル生成物（再生成可能）
    if top == "dynamicCode":
        return "dynamicCode", False
    # ケース内に入れ子になった別ケース（それ自体を別 run として登録・保存する）
    if len(parts) > 1 and os.path.isfile(os.path.join(case, top, "system", "controlDict")):
        return f"nested-case:{top}", False
    # VTK
    if top == "VTK":
        return "vtk", bool(opts.include_vtk and "all" in tier.time_dirs)
    # processor*
    if top.startswith("processor"):
        if proc_times is None:
            return "processor", False
        if "*" in proc_times:
            return "processor", True
        sub = parts[1] if len(parts) > 2 else ""
        return "processor", sub == "constant" or sub in proc_times
    # 時刻ディレクトリ
    if M._TIME_RE.match(top) and len(parts) > 1:
        if top == "0":   # 初期条件は minimal の "0/**" で扱う
            return "initial", _matches(rel, inc)
        kind = _field_kind(fn, cfg.les_fields) if len(parts) == 2 else "field"
        cat = {"mean": "les-mean", "rms": "les-rms"}.get(kind, "time-fields")
        if top not in keep_times:
            return cat, False
        if kind == "mean" and not opts.mean:
            return cat, False
        if kind == "rms" and not opts.rms:
            return cat, False
        return cat, True
    # postProcessing
    if top == "postProcessing" and len(parts) > 2:
        func = parts[1]
        if func.startswith("surfaces"):
            if surf_all:
                return "pp:surfaces", True
            if surf_latest:
                tdirs = M.time_dirs(os.path.join(case, "postProcessing", func))
                return "pp:surfaces", bool(tdirs) and parts[2] == tdirs[-1]
            return "pp:surfaces", False
        if opts.acoustic_series and func.startswith(("probes", "forceCoeffs")):
            return f"pp:{func}", True
        return f"pp:{func}", _matches(rel, inc)
    if rel.startswith("constant/polyMesh/"):
        return "mesh", _matches(rel, inc)
    return "case-files", _matches(rel, inc)


def _figure_files(cfg: Config, meta: dict, repo: str) -> list[str]:
    """docs/figures 直下で "<case名>*"（末尾 _test を除いた名前も）に一致するもの + extra.figures。"""
    fdir = os.path.join(repo, cfg.raw.get("figures_dir", "docs/figures"))
    if not os.path.isdir(fdir):
        return []
    name = meta.get("case_name", "")
    prefixes = {name, re.sub(r"_test$", "", name)} - {""}
    pats = [f"{p}*" for p in prefixes] + list((meta.get("extra") or {}).get("figures") or [])
    out = set()
    for entry in os.listdir(fdir):
        if not any(fnmatch.fnmatch(entry, p) for p in pats):
            continue
        p = os.path.join(fdir, entry)
        if os.path.isfile(p):
            out.add(p)
        else:
            out |= {os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs if f != ".DS_Store"}
    return sorted(out)
