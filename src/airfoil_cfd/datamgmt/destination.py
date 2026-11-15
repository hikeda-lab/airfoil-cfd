"""アーカイブ先（外付け HDD）の接続・同一性・空き容量チェック。チェック自体は読み取り専用。

どれか 1 つでも満たさなければアーカイブは失敗扱い（元データには触れない）。
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import yaml

from airfoil_cfd.datamgmt.config import Config

SENTINEL = ".archive-root.yaml"
EXIT_DEST_UNAVAILABLE = 2


@dataclass
class DestStatus:
    ok: bool
    mount: str | None
    root: str | None
    free_bytes: int | None = None
    volume_uuid: str | None = None
    initialized: bool = False
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def volume_uuid(mount: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["diskutil", "info", "-plist", mount], capture_output=True, timeout=20)
        info = plistlib.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException):
        return None
    return info.get("VolumeUUID")


def check(cfg: Config, required_bytes: int = 0, *, need_initialized: bool = True) -> DestStatus:
    mount, root = cfg.mount, cfg.archive_root
    # テスト用に false にできる。本番は常に true（ただのディレクトリへの誤書き込みを防ぐ）
    is_mount_required = (cfg.raw.get("destination") or {}).get("require_mountpoint", True)
    st = DestStatus(ok=False, mount=mount, root=root)
    if not mount:
        st.problems.append("destination.mount が未設定です（config/archive.local.yaml）")
        return st
    if not os.path.isdir(mount):
        st.problems.append(f"HDD が接続されていません: {mount} が存在しません")
        return st
    if is_mount_required and not os.path.ismount(mount):
        st.problems.append(f"{mount} はマウントポイントではありません（HDD 未接続の可能性）")
        return st
    st.volume_uuid = volume_uuid(mount)
    if cfg.volume_uuid and st.volume_uuid and cfg.volume_uuid != st.volume_uuid:
        st.problems.append(f"ボリューム UUID 不一致: 期待 {cfg.volume_uuid} / 実際 {st.volume_uuid}")
    elif not cfg.volume_uuid:
        st.notes.append("volume_uuid 未設定のため照合をスキップ（archive init で記録されます）")
    sentinel = os.path.join(root, SENTINEL)
    st.initialized = os.path.isfile(sentinel)
    if st.initialized and st.volume_uuid:
        with open(sentinel) as f:
            s = yaml.safe_load(f) or {}
        if s.get("volume_uuid") and s["volume_uuid"] != st.volume_uuid:
            st.problems.append("センチネルの UUID がボリュームと一致しません（別ディスクのコピー?）")
    if need_initialized and not st.initialized:
        st.problems.append(f"アーカイブルート未初期化: {root}（`afcfd archive init --execute`）")
    st.free_bytes = shutil.disk_usage(mount).free
    need = int(required_bytes * cfg.free_space_margin)
    if required_bytes and st.free_bytes < need:
        st.problems.append(f"空き容量不足: 必要 {human(need)} / 空き {human(st.free_bytes)}")
    st.ok = not st.problems
    return st


def human(n: float | int | None) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
