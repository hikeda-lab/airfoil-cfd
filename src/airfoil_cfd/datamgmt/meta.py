"""run メタデータ（run.yaml）の自動抽出と run ID 生成。ケースディレクトリは読むだけ。"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import math
import os
import re
import subprocess

from airfoil_cfd.datamgmt import foamdict as fd

SCHEMA_VERSION = 1
_TIME_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_SOLVER_LOGS = ("log.foamRun", "foamRun.log", "log.simpleFoam", "log.pimpleFoam")


# --------------------------------------------------------------------------- #
# ケース構造
# --------------------------------------------------------------------------- #
def time_dirs(path: str) -> list[str]:
    """数値名ディレクトリ（時刻）を数値順で返す。"""
    try:
        names = os.listdir(path)
    except OSError:
        return []
    ts = [n for n in names if _TIME_RE.match(n) and os.path.isdir(os.path.join(path, n))]
    return sorted(ts, key=float)


def processor_dirs(case: str) -> list[str]:
    return sorted(d for d in glob.glob(os.path.join(case, "processor*")) if os.path.isdir(d))


def reconstruct_status(case: str) -> dict:
    """processor* の時刻がケース直下に全て reconstruct 済みか。"""
    procs = processor_dirs(case)
    if not procs:
        return {"decomposed": False, "reconstructed": True, "missing_times": []}
    root = set(time_dirs(case))
    ptimes = set(time_dirs(procs[0]))
    missing = sorted((ptimes - root) - {"0"}, key=float)
    return {"decomposed": True, "n_processors": len(procs),
            "reconstructed": not missing, "missing_times": missing}


def solver_log(case: str) -> str | None:
    for name in _SOLVER_LOGS:
        p = os.path.join(case, name)
        if os.path.isfile(p):
            return p
    for p in sorted(glob.glob(os.path.join(case, "log.*")) + glob.glob(os.path.join(case, "*.log"))):
        if fd.log_header(p).get("exec") == "foamRun":
            return p
    return None


def _force_coeffs_dat(case: str) -> str | None:
    c = sorted(glob.glob(os.path.join(case, "postProcessing", "forceCoeffs*", "*", "*.dat")))
    return c[-1] if c else None


# --------------------------------------------------------------------------- #
# Git
# --------------------------------------------------------------------------- #
def _git(repo: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_info(repo: str, at: dt.datetime | None = None) -> dict:
    """at=None: 現在の HEAD（register 時）。at 指定: その時刻以前の最新コミット（ingest 時の推定）。"""
    if at is None:
        porcelain = _git(repo, "status", "--porcelain", "--untracked-files=no") or ""
        return {
            "sha": _git(repo, "rev-parse", "HEAD"),
            "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(porcelain),
            "dirty_files": [ln[3:] for ln in porcelain.splitlines()][:50],
            "dirty_hash": hashlib.sha256(porcelain.encode()).hexdigest()[:12] if porcelain else None,
            "source": "HEAD-at-register",
        }
    sha = _git(repo, "rev-list", "-1", f"--before={at.isoformat()}", "HEAD")
    return {"sha": sha or None, "branch": None, "dirty": None,
            "source": "inferred-by-date" if sha else "unknown(before-first-commit)"}


# --------------------------------------------------------------------------- #
# 個別抽出
# --------------------------------------------------------------------------- #
def _created(case: str, log: str | None) -> tuple[dt.datetime, str]:
    if log:
        h = fd.log_header(log)
        if h.get("date") and h.get("time"):
            try:
                return dt.datetime.strptime(f"{h['date']} {h['time']}", "%b %d %Y %H:%M:%S"), "log"
            except ValueError:
                pass
    for p in (os.path.join(case, "system", "controlDict"), case):
        if os.path.exists(p):
            return dt.datetime.fromtimestamp(os.path.getmtime(p)), "mtime"
    return dt.datetime.now(), "now"


def _physics(case: str, fc_hdr: dict) -> dict:
    u_txt = fd.read_text(os.path.join(case, "0", "U")) or fd.read_text(
        os.path.join(case, "0.orig", "U"))
    uvec, src = None, None
    if u_txt:
        bf = fd.block(u_txt, "boundaryField") or ""
        for name in ("inlet", "freestream", "inflow", "farfield"):
            b = fd.block(bf, name)
            if b:
                uvec = fd.vector(fd.value(b, "freestreamValue") or fd.value(b, "value") or "")
                if uvec:
                    src = f"0/U:{name}"
                    break
        if uvec is None:
            uvec = fd.vector(fd.value(u_txt, "internalField"))
            src = "0/U:internalField" if uvec else None
    alpha = umag = None
    if uvec:
        umag = math.sqrt(sum(c * c for c in uvec))
        cross = uvec[1] if abs(uvec[1]) >= abs(uvec[2]) else uvec[2]
        alpha = math.degrees(math.atan2(cross, uvec[0]))
    elif u_txt and fd.number(u_txt, "speed") is not None:   # チュートリアルの #calc 形式
        umag, alpha, src = fd.number(u_txt, "speed"), fd.number(u_txt, "angleOfAttack"), "0/U:speed"
    if umag is None and isinstance(fc_hdr.get("magUInf"), float):
        umag, src = fc_hdr["magUInf"], "forceCoeffs:magUInf"
    nu = fd.number(fd.read_text(os.path.join(case, "constant", "physicalProperties")), "nu")
    lref = fc_hdr.get("lRef") if isinstance(fc_hdr.get("lRef"), float) else None
    re_ = umag * lref / nu if (umag and lref and nu) else None
    r = lambda x, n=6: round(x, n) if isinstance(x, float) else x  # noqa: E731
    return {"U_inf": r(umag), "alpha_deg": r(alpha, 4), "U_vector": list(uvec) if uvec else None,
            "U_source": src, "nu": nu, "lRef": lref,
            "Aref": fc_hdr.get("Aref") if isinstance(fc_hdr.get("Aref"), float) else None,
            "Re": round(re_) if re_ else None,
            "magUInf_forceCoeffs": fc_hdr.get("magUInf"),
            "dragDir": list(fc_hdr["dragDir"]) if isinstance(fc_hdr.get("dragDir"), tuple) else None,
            "liftDir": list(fc_hdr["liftDir"]) if isinstance(fc_hdr.get("liftDir"), tuple) else None}


def _turbulence(case: str) -> dict:
    t = fd.read_text(os.path.join(case, "constant", "momentumTransport"))
    sim = fd.value(t, "simulationType")
    sub = fd.block(t, sim) if sim and sim != "laminar" else None
    return {"simulationType": sim, "model": fd.value(sub, "model"),
            "delta": fd.value(sub, "delta")}


def _time(case: str, log: str | None) -> dict:
    c = fd.read_text(os.path.join(case, "system", "controlDict"))
    tds = time_dirs(case)
    return {
        "solver": fd.value(c, "solver") or fd.value(c, "application"),
        "deltaT": fd.number(c, "deltaT"), "endTime": fd.number(c, "endTime"),
        "adjustTimeStep": fd.value(c, "adjustTimeStep"), "maxCo": fd.number(c, "maxCo"),
        "writeControl": fd.value(c, "writeControl"), "writeInterval": fd.number(c, "writeInterval"),
        "writeFormat": fd.value(c, "writeFormat"),
        "last_log_time": fd.log_tail_time(log) if log else None,
        "time_dirs": len(tds), "latest_time": tds[-1] if tds else None,
    }


def _mesh(case: str) -> dict:
    sysd = os.path.join(case, "system")
    has = lambda *ps: any(os.path.exists(os.path.join(case, p)) for p in ps)  # noqa: E731
    if has("system/snappyHexMeshDict") and has("log.snappyHexMesh", "snappyHexMesh.log",
                                                  "constant/polyMesh/cellLevel"):
        method = "snappyHexMesh"
    elif has("system/extrudeMeshDict"):
        method = "blockMesh+extrudeMesh"
    elif has("system/blockMeshDict"):
        method = "blockMesh"
    else:
        method = "prebuilt/unknown"
    pm = os.path.join(case, "constant", "polyMesh")
    if not os.path.isdir(pm):
        procs = processor_dirs(case)
        pm = os.path.join(procs[0], "constant", "polyMesh") if procs else pm
    counts = fd.mesh_counts(os.path.join(pm, "owner"))
    btxt = fd.read_text(os.path.join(pm, "boundary")) or ""
    types = sorted(set(re.findall(r"\btype\s+(\w+);", btxt)))
    dim = "2D" if "empty" in types else ("3D-periodic" if "cyclic" in types else "3D")
    checks = sorted(glob.glob(os.path.join(case, "log.checkMesh*")) +
                    glob.glob(os.path.join(case, "checkMesh*.log")))
    cm = _checkmesh(checks[-1]) if checks else None
    stls = [os.path.relpath(p, case) for p in glob.glob(os.path.join(case, "constant", "**", "*.stl"),
                                                       recursive=True)]
    return {"method": method, "dimension": dim, "patch_types": types,
            "cells": counts.get("nCells"), "points": counts.get("nPoints"),
            "faces": counts.get("nFaces"),
            "cells_source": "processor0 only" if pm != os.path.join(case, "constant", "polyMesh")
            and counts else None,
            "checkMesh": cm, "stl": stls, "has_dicts": sorted(os.listdir(sysd)) if os.path.isdir(sysd)
            else []}


def _checkmesh(path: str) -> dict:
    t = fd.read_text(path) or ""
    g = lambda pat: (lambda m: float(m.group(1)) if m else None)(re.search(pat, t))  # noqa: E731
    return {"log": os.path.basename(path), "ok": "Mesh OK." in t,
            "failed_checks": int(m.group(1)) if (m := re.search(r"Failed (\d+) mesh checks", t)) else 0,
            "max_non_orthogonality": g(r"Mesh non-orthogonality Max:\s*([\d.eE+-]+)"),
            "max_skewness": g(r"Max skewness = ([\d.eE+-]+)"),
            "max_aspect_ratio": g(r"Max aspect ratio = ([\d.eE+-]+)")}


def _outputs(case: str) -> dict:
    pp = os.path.join(case, "postProcessing")
    funcs = sorted(os.listdir(pp)) if os.path.isdir(pp) else []
    tds = time_dirs(case)
    latest = [f for f in os.listdir(os.path.join(case, tds[-1]))] if tds else []
    return {"postProcessing": funcs,
            "latest_fields": sorted(f for f in latest if not f.startswith(".")),
            "has_mean": any(f.endswith("Mean") and "Prime2" not in f for f in latest),
            "has_rms": any(f.endswith("Prime2Mean") for f in latest),
            "has_probes": any(f.startswith("probes") for f in funcs),
            "has_surfaces": any(f.startswith("surfaces") for f in funcs),
            "has_vtk": os.path.isdir(os.path.join(case, "VTK"))}


def _results(case: str, transient: bool) -> dict:
    try:
        from airfoil_cfd import postprocess   # 既存の Cl/Cd 集計をそのまま使う
        s = postprocess.force_summary(case, transient=transient)
        s = {k: round(v, 6) for k, v in s.items()}
        s["method"] = "mean/std over latter 50%" if transient else "final value"
        return s
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _geometry(case_name: str) -> dict:
    m = re.search(r"(naca\d{4,5}|sd\d{4}|e\d{3}|s\d{4}|clarky)", case_name.lower())
    return {"kind": "airfoil", "airfoil": m.group(1) if m else None, "source": "case-name"}


# --------------------------------------------------------------------------- #
# run ID / 全体
# --------------------------------------------------------------------------- #
def make_run_id(case_name: str, created: dt.datetime, fingerprint: dict) -> str:
    """`YYYYMMDD-HHMMSS_<case-slug>_<6桁ハッシュ>`。ハッシュは fingerprint（ケースパス+開始時刻）から。"""
    slug = re.sub(r"[^a-z0-9]+", "-", case_name.lower()).strip("-")
    h = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, default=str).encode()).hexdigest()
    return f"{created:%Y%m%d-%H%M%S}_{slug}_{h[:6]}"


def extract(case: str, repo: str, *, infer_git: bool = False, notes: str | None = None) -> dict:
    """ケースから run.yaml 用の辞書を作る。infer_git=True は過去 run の取り込み（ingest）用。"""
    case = os.path.abspath(case)
    name = os.path.basename(case.rstrip("/"))
    log = solver_log(case)
    created, created_src = _created(case, log)
    fc = _force_coeffs_dat(case)
    fc_hdr = fd.force_coeffs_header(fc) if fc else {}
    turb = _turbulence(case)
    tm = _time(case, log)
    hdr = fd.log_header(log) if log else {}
    git = git_info(repo, at=created if infer_git else None)
    physics = _physics(case, fc_hdr)
    rel = os.path.relpath(case, repo)
    meta = {
        "schema": SCHEMA_VERSION,
        "run_id": None,
        "case_name": name,
        "case_path": {"host": rel if not rel.startswith("..") else case,
                      "vm": hdr.get("case")},
        "created": created.isoformat(timespec="seconds"),
        "created_source": created_src,
        "registered": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "finished" if tm["latest_time"] not in (None, "0") else "registered",
        "provenance": "ingested(inferred)" if infer_git else "registered",
        "notes": notes,
        "git": git,
        "openfoam": {"version": hdr.get("version"), "build": hdr.get("build"),
                     "exec": hdr.get("exec"), "nProcs": int(hdr["nprocs"]) if hdr.get("nprocs")
                     else None, "host": hdr.get("host"),
                     "log": os.path.basename(log) if log else None},
        "geometry": _geometry(name),
        "physics": physics,
        "turbulence": turb,
        "time": tm,
        "mesh": _mesh(case),
        "decomposition": reconstruct_status(case),
        "outputs": _outputs(case),
        "results": _results(case, transient=(turb.get("simulationType") == "LES")),
        "extra_paths": [],     # ケース外の関連データ（例: docs/figures/vtk）。repo 相対
        "extra": {},           # クロスフローファン等の拡張（回転数, MRF/AMI ...）
        "archive": {"copies": []},
    }
    # 同一性は「どのケースを・いつ計算したか」だけで決める（抽出ロジックを改良しても ID が変わらない）
    meta["run_id"] = make_run_id(name, created, {
        "case": meta["case_path"]["host"], "created": meta["created"]})
    return meta


def is_les(meta: dict) -> bool:
    return (meta.get("turbulence") or {}).get("simulationType") == "LES"
