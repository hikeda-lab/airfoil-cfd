"""HDD アーカイブ: init / push（コピー→HDD から再読込してハッシュ検証→確定）/ verify。

安全原則:
  - 保存先チェック（接続・マウント・UUID・センチネル・空き容量）に失敗したら何もしない（終了コード 2）。
  - コピーは staging/<run_id>.partial へ。全ファイルを HDD から読み直して sha256 一致を確認してから
    runs/<run_id> へ rename で確定する。失敗時は partial を残して報告する。
  - 元データ（ケースディレクトリ）は読むだけ。削除は一切しない（prune は別コマンド・要承認）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys

import yaml

from airfoil_cfd.datamgmt import destination as D
from airfoil_cfd.datamgmt import registry as R
from airfoil_cfd.datamgmt import tiers as T
from airfoil_cfd.datamgmt.config import Config

MANIFEST = "MANIFEST.sha256"
DATA = "data"
CHUNK = 8 * 1024 * 1024


class ArchiveError(RuntimeError):
    exit_code = 1


class DestinationUnavailable(ArchiveError):
    exit_code = D.EXIT_DEST_UNAVAILABLE


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# ハッシュ
# --------------------------------------------------------------------------- #
def _open_nocache(path: str):
    """検証用: macOS ではページキャッシュを使わず実際にディスクから読む。"""
    f = open(path, "rb")
    if sys.platform == "darwin":
        import fcntl
        try:
            fcntl.fcntl(f.fileno(), fcntl.F_NOCACHE, 1)
        except OSError:
            pass
    return f


def sha256_file(path: str, nocache: bool = False) -> str:
    h = hashlib.sha256()
    with (_open_nocache(path) if nocache else open(path, "rb")) as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def copy_hash(src: str, dst: str) -> str:
    """src を読みながら sha256 を計算して dst へ書く（1 回の読み込みで済ませる）。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    h = hashlib.sha256()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while chunk := fi.read(CHUNK):
            h.update(chunk)
            fo.write(chunk)
        fo.flush()
        os.fsync(fo.fileno())
    shutil.copystat(src, dst)
    return h.hexdigest()


def read_manifest(path: str) -> dict[str, str]:
    out = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line:
                digest, rel = line.split("  ", 1)
                out[rel] = digest
    return out


def write_manifest(path: str, entries: dict[str, str]) -> str:
    text = "".join(f"{d}  {rel}\n" for rel, d in sorted(entries.items()))
    with open(path, "w") as f:
        f.write(text)
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def init(cfg: Config, execute: bool) -> D.DestStatus:
    st = D.check(cfg, need_initialized=False)
    if not st.ok:
        raise DestinationUnavailable("; ".join(st.problems))
    if st.initialized:
        print(f"初期化済み: {st.root}")
        return st
    print(f"作成予定: {st.root}/{{runs,staging}}, {D.SENTINEL}, catalog.jsonl")
    if not execute:
        print("[dry-run] --execute で作成します。")
        return st
    for d in ("runs", "staging"):
        os.makedirs(os.path.join(st.root, d), exist_ok=True)
    with open(os.path.join(st.root, D.SENTINEL), "w") as f:
        yaml.safe_dump({"schema": 1, "created": now(), "volume_uuid": st.volume_uuid,
                        "mount": st.mount, "project": "airfoil-cfd"}, f, sort_keys=False)
    open(os.path.join(st.root, "catalog.jsonl"), "a").close()
    st.initialized = True
    print(f"作成しました: {st.root}")
    return st


# --------------------------------------------------------------------------- #
# 1 箇所へのコピー（HDD・ミラー共通）
# --------------------------------------------------------------------------- #
def _copy_verified(sel: T.Selection, meta: dict, dest_runs: str, staging: str, kind: str,
                   log=print) -> dict:
    run_id = meta["run_id"]
    final = os.path.join(dest_runs, run_id)
    part = os.path.join(staging, f"{run_id}.partial")
    if os.path.exists(part):
        raise ArchiveError(f"前回の未完了コピーが残っています: {part}\n"
                           f"  内容を確認し、不要なら手動で削除してから再実行してください。")
    os.makedirs(part)
    t0 = dt.datetime.now()
    before = {e.src: (e.size, os.stat(e.src).st_mtime_ns) for e in sel.selected}
    digests: dict[str, str] = {}
    total, done = sel.selected_bytes, 0
    for i, e in enumerate(sel.selected, 1):
        rel = f"{DATA}/{e.arc}"
        digests[rel] = copy_hash(e.src, os.path.join(part, rel))
        done += e.size
        if i % 200 == 0 or e.size > 50 * 2**20:
            log(f"    [{kind}] copy {i}/{len(sel.selected)} files  "
                f"{D.human(done)}/{D.human(total)}")
    # 元データがコピー中に変わっていないか
    changed = [s for s, (sz, mt) in before.items()
               if (lambda st_: (st_.st_size, st_.st_mtime_ns))(os.stat(s)) != (sz, mt)]
    if changed:
        raise ArchiveError(f"コピー中に元ファイルが変更されました（計算中?）: {changed[:5]}  "
                           f"partial を残しました: {part}")
    # HDD から読み直して検証
    log(f"    [{kind}] verify {len(digests)} files（保存先から再読込）")
    bad = [rel for rel, d in digests.items()
           if sha256_file(os.path.join(part, rel), nocache=True) != d]
    if bad:
        raise ArchiveError(f"ハッシュ不一致 {len(bad)} 件: {bad[:5]}  partial を残しました: {part}")
    msha = write_manifest(os.path.join(part, MANIFEST), digests)
    copy = {"kind": kind, "tier": sel.tier, "path": final, "archived_at": now(),
            "files": len(digests), "bytes": total, "manifest_sha256": msha,
            "seconds": round((dt.datetime.now() - t0).total_seconds(), 1),
            "snapshot_times": sel.snapshot_times, "warnings": sel.warnings}
    # 既存（下位レベル等）は消さずに退避して置き換え
    if os.path.exists(final):
        old = f"{final}.superseded-{dt.datetime.now():%Y%m%d-%H%M%S}"
        os.rename(final, old)
        copy["superseded"] = old
        log(f"    [{kind}] 既存コピーを退避: {old}（削除は prune で別途）")
    os.rename(part, final)
    return copy


def _write_run_yaml(path: str, meta: dict):
    with open(os.path.join(path, "run.yaml"), "w") as f:
        f.write(R.dump(meta))


# --------------------------------------------------------------------------- #
# push
# --------------------------------------------------------------------------- #
def push(cfg: Config, meta: dict, case: str, tier: str, opts: T.Options, execute: bool,
         mirror: bool = True, log=print) -> dict:
    sel = T.select(case, meta, cfg.tiers[tier], cfg, opts)
    st = D.check(cfg, sel.selected_bytes)
    log(f"run {meta['run_id']}  level={tier}  {len(sel.selected)} files {D.human(sel.selected_bytes)}")
    for w in sel.warnings:
        log(f"  注意: {w}")
    if not st.ok:
        raise DestinationUnavailable("保存先が使えません（元データは保持）: " + "; ".join(st.problems))
    existing = [c for c in (meta.get("archive") or {}).get("copies") or []
                if c.get("kind") == "hdd" and os.path.isdir(c.get("path", ""))]
    if existing:
        log(f"  既存の HDD コピー: {existing[-1]['tier']} ({existing[-1]['archived_at']})"
            f" → 新しいコピーで置き換え（旧コピーは退避）")
    mirror_sel = None
    if mirror and cfg.mirrors:
        mirror_sel = T.select(case, meta, cfg.tiers[cfg.mirror_tier], cfg, opts)
        for m in cfg.mirrors:
            log(f"  ミラー: {m}/runs/{meta['run_id']}  level={cfg.mirror_tier} "
                f"{D.human(mirror_sel.selected_bytes)}")
    if not execute:
        log("[dry-run] --execute でコピー・検証します（元データは削除しません）。")
        return {}

    copies = []
    hdd = _copy_verified(sel, meta, os.path.join(st.root, "runs"),
                         os.path.join(st.root, "staging"), "hdd", log)
    hdd["volume_uuid"] = st.volume_uuid
    copies.append(hdd)
    log(f"  ✓ HDD: {hdd['path']}  ({hdd['files']} files, {D.human(hdd['bytes'])}, "
        f"{hdd['seconds']} s)")
    mirror_errors = []
    for m in (cfg.mirrors if mirror_sel else []):
        try:
            os.makedirs(os.path.join(m, "runs"), exist_ok=True)
            os.makedirs(os.path.join(m, "staging"), exist_ok=True)
            mc = _copy_verified(mirror_sel, meta, os.path.join(m, "runs"),
                                os.path.join(m, "staging"), "mirror", log)
            copies.append(mc)
            log(f"  ✓ ミラー: {mc['path']}  ({mc['files']} files, {D.human(mc['bytes'])})")
        except (OSError, ArchiveError) as e:
            mirror_errors.append(f"{m}: {e}")
            log(f"  ✗ ミラー失敗: {m}: {e}")

    # メタデータ更新（同じ場所の古い記録は置き換え）
    paths = {c["path"] for c in copies}
    arch = meta.setdefault("archive", {})
    arch["copies"] = [c for c in arch.get("copies") or [] if c.get("path") not in paths] + copies
    meta["status"] = "archived"
    for c in copies:
        _write_run_yaml(c["path"], meta)
    with open(os.path.join(st.root, "catalog.jsonl"), "a") as f:
        f.write(json.dumps({"run_id": meta["run_id"], "case": meta["case_name"], "tier": tier,
                            "archived_at": hdd["archived_at"], "files": hdd["files"],
                            "bytes": hdd["bytes"], "manifest_sha256": hdd["manifest_sha256"],
                            "turbulence": meta.get("turbulence"),
                            "alpha_deg": (meta.get("physics") or {}).get("alpha_deg")},
                           ensure_ascii=False) + "\n")
    R.write(meta, case, cfg)
    if mirror_errors:
        raise ArchiveError("HDD への保存は成功しましたが、ミラーに失敗しました: "
                           + "; ".join(mirror_errors))
    return meta


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def verify_dir(path: str, log=print) -> bool:
    mpath = os.path.join(path, MANIFEST)
    if not os.path.isfile(mpath):
        log(f"  ✗ MANIFEST がありません: {mpath}")
        return False
    want = read_manifest(mpath)
    have = {os.path.relpath(os.path.join(d, f), path).replace(os.sep, "/")
            for d, _, fs in os.walk(os.path.join(path, DATA)) for f in fs}
    missing = sorted(set(want) - have)
    extra = sorted(have - set(want))
    bad = [rel for rel in sorted(set(want) & have)
           if sha256_file(os.path.join(path, rel), nocache=True) != want[rel]]
    ok = not (missing or bad)
    log(f"  {'✓' if ok else '✗'} {path}: {len(want)} files, 欠損 {len(missing)}, "
        f"不一致 {len(bad)}, 余分 {len(extra)}")
    for rel in (missing[:10] + bad[:10]):
        log(f"      {'欠損' if rel in missing else '不一致'}: {rel}")
    for rel in extra[:10]:
        log(f"      余分（MANIFEST 外）: {rel}")
    return ok


def verify(cfg: Config, meta: dict, log=print) -> bool:
    copies = (meta.get("archive") or {}).get("copies") or []
    if not copies:
        raise ArchiveError(f"アーカイブ記録がありません: {meta['run_id']}")
    ok = True
    for c in copies:
        if c["kind"] == "hdd":
            st = D.check(cfg)
            if not st.ok:
                raise DestinationUnavailable("; ".join(st.problems))
        if not os.path.isdir(c["path"]):
            log(f"  ✗ [{c['kind']}] コピーが見つかりません: {c['path']}")
            ok = False
            continue
        log(f"  [{c['kind']}:{c['tier']}]")
        ok &= verify_dir(c["path"], log)
    return ok
