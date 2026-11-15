"""`afcfd runs ...` / `afcfd archive ...` サブコマンド。書き込みは --execute 指定時のみ。"""
from __future__ import annotations

import os
import sys

from airfoil_cfd.datamgmt import archive as A
from airfoil_cfd.datamgmt import config as C
from airfoil_cfd.datamgmt import destination as D
from airfoil_cfd.datamgmt import registry as R
from airfoil_cfd.datamgmt import tiers as T

human = D.human


def _case_dir(cfg: C.Config, arg: str) -> str | None:
    for p in (arg, os.path.join(cfg.path("cases_dir"), arg)):
        if os.path.isfile(os.path.join(p, "system", "controlDict")):
            return os.path.abspath(p)
    return None


def _resolve(cfg: C.Config, arg: str) -> tuple[dict, str]:
    """引数（ケースパス/ケース名/run_id）→ (meta, case_dir)。未登録ケースはその場で抽出（書かない）。"""
    case = _case_dir(cfg, arg)
    if case:
        meta = R.case_meta(case) or R.build(case, cfg, infer_git=True)
        return meta, case
    meta = R.resolve(cfg, arg)
    host = (meta.get("case_path") or {}).get("host") or ""
    case = host if os.path.isabs(host) else os.path.join(cfg.repo, host)
    return meta, case


def _summary_line(m: dict) -> str:
    t, p = m.get("turbulence") or {}, m.get("physics") or {}
    re_ = p.get("Re")
    return (f"{t.get('simulationType') or '?'} {t.get('model') or ''}  "
            f"α={p.get('alpha_deg')}°  U={p.get('U_inf')}  Re={f'{re_:.3g}' if re_ else '?'}  "
            f"mesh={(m.get('mesh') or {}).get('cells') or '?'} cells "
            f"({(m.get('mesh') or {}).get('method')})")


# --------------------------------------------------------------------------- #
# runs
# --------------------------------------------------------------------------- #
def _cmd_register(a, finalize=False):
    cfg = C.load()
    case = _case_dir(cfg, a.case)
    if not case:
        sys.exit(f"ケースが見つかりません（system/controlDict が必要）: {a.case}")
    meta = R.build(case, cfg, infer_git=a.infer_git, notes=a.notes)
    for ep in a.extra_path or []:
        if ep not in [x if isinstance(x, str) else x.get("path") for x in meta["extra_paths"]]:
            meta["extra_paths"].append({"path": ep, "tier": a.extra_tier})
    if finalize and meta["status"] != "archived":
        meta["status"] = "finished"
    print(f"run_id: {meta['run_id']}\n  {_summary_line(meta)}\n  git: {meta['git'].get('sha')} "
          f"({meta['git'].get('source')}{', dirty' if meta['git'].get('dirty') else ''})")
    if meta["git"].get("dirty"):
        print("  警告: 作業ツリーに未コミット変更があります（git.dirty_files に記録）")
    if not a.execute:
        print("[dry-run] 書き込みません。--execute で registry とケース内 run.yaml を書きます。")
        if a.verbose:
            print(R.dump(meta))
        return
    for p in R.write(meta, case, cfg):
        print(f"  wrote {os.path.relpath(p, cfg.repo)}")


def _cmd_list(a):
    cfg = C.load()
    runs = [r for r in R.all_runs(cfg) if R.matches(r, a.where or [], a.grep)]
    if a.turb:
        runs = [r for r in runs if (r.get("turbulence") or {}).get("simulationType", "").lower()
                == a.turb.lower()]
    if a.airfoil:
        runs = [r for r in runs if a.airfoil.lower() in str((r.get("geometry") or {})
                                                            .get("airfoil")).lower()]
    if a.status:
        runs = [r for r in runs if r.get("status") == a.status]
    if not runs:
        print("該当する run はありません（`afcfd runs ingest` で既存ケースを登録できます）")
        return
    print(f"{'run_id':58} {'turb':20} {'α':>6} {'Cl':>9} {'Cd':>9} {'status':9} copies")
    for r in runs:
        t, p, res = r.get("turbulence") or {}, r.get("physics") or {}, r.get("results") or {}
        f = lambda x: f"{x:9.4f}" if isinstance(x, (int, float)) else f"{'-':>9}"  # noqa: E731
        al = p.get("alpha_deg")
        print(f"{r['run_id']:58} {(t.get('simulationType') or '?') + ':' + (t.get('model') or ''):20}"
              f" {al if al is not None else '-':>6} {f(res.get('Cl'))} {f(res.get('Cd'))} "
              f"{r.get('status', '?'):9} {R.copies_summary(r)}")


def _cmd_show(a):
    cfg = C.load()
    meta, _ = _resolve(cfg, a.run)
    print(R.dump(meta))


def _cmd_ingest(a):
    cfg = C.load()
    root = os.path.abspath(a.scan or cfg.path("cases_dir"))
    cases = []
    for dirpath, dirnames, _ in os.walk(root):
        if os.path.isfile(os.path.join(dirpath, "system", "controlDict")):
            cases.append(dirpath)
            dirnames[:] = []   # ケースの中は掘らない
            continue
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(("processor", ".")))
        if dirpath.count(os.sep) - root.count(os.sep) >= 3:
            dirnames[:] = []
    known = {r["run_id"] for r in R.all_runs(cfg)}
    print(f"スキャン: {root}  ケース {len(cases)} 件")
    for case in sorted(cases):
        meta = R.build(case, cfg, infer_git=True)
        state = "registered" if meta["run_id"] in known else "new"
        print(f"  [{state:10}] {meta['run_id']}\n               {_summary_line(meta)}")
        if a.execute and state == "new":
            R.write(meta, case, cfg)
    if not a.execute:
        print("[dry-run] --execute で未登録ケースを registry/runs と各ケースの run.yaml に書きます。")


# --------------------------------------------------------------------------- #
# archive plan
# --------------------------------------------------------------------------- #
def _opts(a) -> T.Options:
    snaps = None
    if a.snapshots:
        snaps = [] if a.snapshots == "none" else [s.strip() for s in a.snapshots.split(",")]
    return T.Options(snapshots=snaps, n_snapshots=a.n_snapshots, mean=not a.no_mean,
                     rms=not a.no_rms, acoustic_series=a.acoustic_series,
                     include_vtk=a.include_vtk)


def _cmd_plan(a):
    cfg = C.load()
    meta, case = _resolve(cfg, a.run)
    if not os.path.isdir(case):
        sys.exit(f"ケースディレクトリがありません: {case}")
    opts = _opts(a)
    sels = {name: T.select(case, meta, tier, cfg, opts) for name, tier in cfg.tiers.items()}
    sel = sels[a.level]
    total = sel.selected_bytes + sel.skipped_bytes
    print(f"run   : {meta['run_id']}\ncase  : {case}\n        {_summary_line(meta)}")
    print(f"総量  : {human(total)}（{len(sel.selected) + len(sel.skipped)} files）")
    st = D.check(cfg, sel.selected_bytes)
    mark = "OK" if st.ok else "NG"
    print(f"保存先: {st.root or '(未設定)'}  [{mark}]  空き {human(st.free_bytes)}")
    for p in st.problems:
        print(f"        ✗ {p}")
    for n in st.notes:
        print(f"        - {n}")
    print("\n保存レベル別:")
    for name, s in sels.items():
        mark = "→" if name == a.level else " "
        print(f" {mark} {name:9} {len(s.selected):7d} files {human(s.selected_bytes):>10}   "
              f"(残り {human(s.skipped_bytes)})")
    print(f"\n[{a.level}] カテゴリ内訳            保存          保存しない")
    for cat, (sb, sf, kb, kf) in sel.by_category().items():
        print(f"   {cat:26} {human(sb):>10} {sf:6d}f   {human(kb):>10} {kf:6d}f")
    if sel.snapshot_times:
        print(f"\nLES 代表瞬時場: {', '.join(sel.snapshot_times)}")
    for w in sel.warnings:
        print(f"注意: {w}")
    if a.list:
        print("\nファイル一覧:")
        for e in sel.selected:
            print(f"  {human(e.size):>10}  {e.arc}")
    print("\n[dry-run] コピーは行っていません。")


def _run_archive(fn):
    """ArchiveError を終了コード付きで表示（HDD 未接続 = 2、検証失敗等 = 1）。"""
    try:
        return fn()
    except A.ArchiveError as e:
        print(f"失敗: {e}", file=sys.stderr)
        sys.exit(e.exit_code)


def _cmd_init(a):
    cfg = C.load()
    _run_archive(lambda: A.init(cfg, a.execute))


def _cmd_push(a):
    cfg = C.load()
    meta, case = _resolve(cfg, a.run)
    if not R.read_yaml(R.registry_path(cfg, meta["run_id"])):
        sys.exit(f"未登録の run です。先に `afcfd runs register {a.run} --execute` を実行してください。")
    _run_archive(lambda: A.push(cfg, meta, case, a.level, _opts(a), a.execute,
                                mirror=not a.no_mirror))


def _cmd_verify(a):
    cfg = C.load()
    meta = R.resolve(cfg, a.run)
    print(f"verify {meta['run_id']}")
    ok = _run_archive(lambda: A.verify(cfg, meta))
    print("OK: 全コピーが MANIFEST と一致" if ok else "NG: 不一致・欠損があります")
    sys.exit(0 if ok else 1)


def _add_select_opts(p):
    p.add_argument("--level", default="standard", choices=["minimal", "standard", "full"])
    p.add_argument("--snapshots", help="LES 瞬時場の時刻 'a,b,c'（'none' で無し）")
    p.add_argument("--n-snapshots", type=int, help="自動選択する瞬時場の数")
    p.add_argument("--no-mean", action="store_true"); p.add_argument("--no-rms", action="store_true")
    p.add_argument("--acoustic-series", action="store_true",
                   help="surfaces/probes/forceCoeffs の全時系列を含める（音響解析用）")
    p.add_argument("--include-vtk", action="store_true", help="VTK/ を含める（full のみ）")


def add_parsers(sub):
    r = sub.add_parser("runs", help="run メタデータの登録・一覧・検索")
    rs = r.add_subparsers(dest="runs_cmd", required=True)

    for name, fin in (("register", False), ("finalize", True)):
        p = rs.add_parser(name, help="run.yaml を生成/更新" if not fin else "計算後に結果を追記")
        p.add_argument("case"); p.add_argument("--notes")
        p.add_argument("--infer-git", action="store_true",
                       help="git SHA を現在の HEAD ではなく計算日時から推定（過去 run 用）")
        p.add_argument("--extra-path", action="append",
                       help="ケース外の関連データ（repo 相対、例 docs/figures/vtk）")
        p.add_argument("--extra-tier", default="full", choices=["minimal", "standard", "full"])
        p.add_argument("--execute", action="store_true"); p.add_argument("-v", "--verbose",
                                                                         action="store_true")
        p.set_defaults(func=lambda a, f=fin: _cmd_register(a, finalize=f))

    p = rs.add_parser("list", help="登録済み run の一覧・検索")
    p.add_argument("--where", action="append",
                   help="例: turbulence.simulationType=LES / physics.alpha_deg>=10")
    p.add_argument("--grep"); p.add_argument("--turb"); p.add_argument("--airfoil")
    p.add_argument("--status"); p.set_defaults(func=_cmd_list)

    p = rs.add_parser("show", help="run.yaml を表示"); p.add_argument("run")
    p.set_defaults(func=_cmd_show)

    p = rs.add_parser("ingest", help="既存ケースを走査して一括登録（既定 dry-run）")
    p.add_argument("--scan"); p.add_argument("--execute", action="store_true")
    p.set_defaults(func=_cmd_ingest)

    ar = sub.add_parser("archive", help="HDD アーカイブ（plan/push/verify/restore）")
    asub = ar.add_subparsers(dest="archive_cmd", required=True)
    p = asub.add_parser("plan", help="保存対象と容量を表示（コピーしない）")
    p.add_argument("run", help="run_id / ケース名 / ケースパス")
    _add_select_opts(p)
    p.add_argument("--list", action="store_true", help="ファイル一覧も表示")
    p.set_defaults(func=_cmd_plan)

    p = asub.add_parser("init", help="HDD にアーカイブルートとセンチネルを作成")
    p.add_argument("--execute", action="store_true"); p.set_defaults(func=_cmd_init)

    p = asub.add_parser("push", help="保存レベルに従って HDD へコピー＋ハッシュ検証（元データは消さない）")
    p.add_argument("run", help="run_id / ケース名 / ケースパス")
    _add_select_opts(p)
    p.add_argument("--no-mirror", action="store_true", help="SSD ミラーへの複製をしない")
    p.add_argument("--execute", action="store_true"); p.set_defaults(func=_cmd_push)

    p = asub.add_parser("verify", help="保存済みコピーを MANIFEST の sha256 と照合")
    p.add_argument("run"); p.set_defaults(func=_cmd_verify)
