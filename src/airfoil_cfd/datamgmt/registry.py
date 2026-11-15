"""run レジストリ: registry/runs/<run_id>.yaml（git 管理）と ケース内 run.yaml の読み書き・検索。"""
from __future__ import annotations

import glob
import os

import yaml

from airfoil_cfd.datamgmt import meta as M
from airfoil_cfd.datamgmt.config import Config

CASE_META = "run.yaml"
# 再登録しても上書きしない（人手 or アーカイブ処理が書く）キー
_PRESERVE = ("run_id", "notes", "extra_paths", "extra", "archive", "registered", "provenance",
             "git")


def dump(meta: dict) -> str:
    return yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=100)


def read_yaml(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def registry_path(cfg: Config, run_id: str) -> str:
    return os.path.join(cfg.path("registry_dir"), f"{run_id}.yaml")


def case_meta(case: str) -> dict | None:
    return read_yaml(os.path.join(case, CASE_META))


def build(case: str, cfg: Config, *, infer_git: bool = False, notes: str | None = None) -> dict:
    """抽出し直したメタデータに、既存 run.yaml / registry の保存すべき値を引き継ぐ。"""
    new = M.extract(case, cfg.repo, infer_git=infer_git, notes=notes)
    old = case_meta(case)
    if old is None:   # ケース側に無ければ同一 run_id の registry を探す
        old = read_yaml(registry_path(cfg, new["run_id"]))
    if old:
        for k in _PRESERVE:
            if k in old and old[k] not in (None, [], {}):
                if k == "notes" and notes:
                    continue
                new[k] = old[k]
        new["status"] = old.get("status") if old.get("status") == "archived" else new["status"]
    return new


def write(meta: dict, case: str, cfg: Config, *, write_case: bool = True) -> list[str]:
    """registry と（可能なら）ケース内 run.yaml に書く。書いたパスを返す。"""
    out = []
    rp = registry_path(cfg, meta["run_id"])
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    text = dump(meta)
    with open(rp, "w") as f:
        f.write(text)
    out.append(rp)
    if write_case and os.path.isdir(case) and os.access(case, os.W_OK):
        cp = os.path.join(case, CASE_META)
        with open(cp, "w") as f:
            f.write(text)
        out.append(cp)
    return out


def all_runs(cfg: Config) -> list[dict]:
    runs = []
    for p in sorted(glob.glob(os.path.join(cfg.path("registry_dir"), "*.yaml"))):
        d = read_yaml(p)
        if d and d.get("run_id"):
            runs.append(d)
    return runs


def resolve(cfg: Config, key: str) -> dict:
    """run_id（前方一致）・case 名・ケースパスのいずれかから run を一意に引く。"""
    runs = all_runs(cfg)
    exact = [r for r in runs if r["run_id"] == key]
    if exact:
        return exact[0]
    cands = [r for r in runs if r["run_id"].startswith(key) or r.get("case_name") == key
             or (r.get("case_path") or {}).get("host") == key.rstrip("/")]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        raise KeyError(f"run が見つかりません: {key}")
    raise KeyError(f"run が一意に決まりません: {key} → {[r['run_id'] for r in cands]}")


def get_path(d: dict, dotted: str):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def matches(run: dict, where: list[str], text: str | None = None) -> bool:
    """where: ["turbulence.simulationType=LES", "physics.alpha_deg>=10", ...]"""
    for cond in where:
        for op in (">=", "<=", "!=", "=", ">", "<"):
            if op in cond:
                key, val = cond.split(op, 1)
                break
        else:
            raise ValueError(f"条件の書式: key=value / key>=num ...: {cond}")
        got = get_path(run, key.strip())
        val = val.strip()
        if op in ("=", "!="):
            eq = str(got).lower() == val.lower() or (
                isinstance(got, (int, float)) and _num(val) is not None and got == _num(val))
            if eq != (op == "="):
                return False
        else:
            g, v = _num(got), _num(val)
            if g is None or v is None:
                return False
            if not {">=": g >= v, "<=": g <= v, ">": g > v, "<": g < v}[op]:
                return False
    if text:
        blob = dump(run).lower()
        if text.lower() not in blob:
            return False
    return True


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def copies_summary(run: dict) -> str:
    """"hdd:standard,mirror:minimal" のような保存状況。HDD 単独の上位レベルは '!' を付ける。"""
    cps = (run.get("archive") or {}).get("copies") or []
    if not cps:
        return "-"
    s = ",".join(f"{c.get('kind')}:{c.get('tier')}" for c in cps)
    kinds = {c.get("kind") for c in cps}
    return s + ("" if len(kinds) > 1 else " !single-copy")
