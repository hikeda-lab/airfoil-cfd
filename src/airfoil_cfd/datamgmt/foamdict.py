"""OpenFOAM 辞書・ログ・forceCoeffs ヘッダの軽量リーダー（メタデータ抽出用、読み取り専用）。

完全なパーサではない。`key value;` と名前付きブロック `name { ... }` が拾えれば十分という方針で、
読めない値は None を返す（呼び出し側で "unknown" 扱い）。
"""
from __future__ import annotations

import os
import re

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def read_text(path: str) -> str | None:
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def value(text: str | None, key: str) -> str | None:
    """最初に現れる `key value;` の value（文字列）。"""
    if not text:
        return None
    # 行頭 または `;` `{` の直後（1 行に書いたブロック `{ model WALE; delta x; }`）にあるキー
    m = re.search(rf"(?m)(?:^|(?<=[;{{]))\s*{re.escape(key)}\s+([^;{{}}]+);", strip_comments(text))
    return m.group(1).strip() if m else None


def number(text: str | None, key: str) -> float | None:
    v = value(text, key)
    if v is None:
        return None
    m = re.search(rf"({_NUM})\s*$", v)   # 次元付き `nu [0 2 -1 ...] 1.5e-5` も末尾の数を取る
    return float(m.group(1)) if m else None


def block(text: str | None, name: str) -> str | None:
    """`name { ... }` の中身（対応する閉じ括弧まで）。"""
    if not text:
        return None
    t = strip_comments(text)
    m = re.search(rf"(?m)^\s*{re.escape(name)}\s*\{{", t) or re.search(
        rf"(?<![\w.]){re.escape(name)}\s*\{{", t)
    if not m:
        return None
    depth, i0 = 0, m.end() - 1
    for i in range(i0, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                return t[i0 + 1:i]
    return None


def vector(s: str | None) -> tuple[float, float, float] | None:
    if not s:
        return None
    m = re.search(rf"\(\s*({_NUM})\s+({_NUM})\s+({_NUM})\s*\)", s)
    return tuple(float(x) for x in m.groups()) if m else None


# --------------------------------------------------------------------------- #
# ログヘッダ
# --------------------------------------------------------------------------- #
def log_header(path: str) -> dict:
    """OpenFOAM アプリのログ先頭バナー（Version/Build/Exec/Date/Time/Host/nProcs/Case）。"""
    lines: list[str] = []
    try:
        with open(path, errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 60:
                    break
                lines.append(line)
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return {}
    out: dict = {}
    for line in lines:
        m = re.search(r"Version:\s*(\S+)", line)
        if m and "version" not in out:
            out["version"] = m.group(1)
        m = re.match(r"^(Build|Exec|Date|Time|Host|nProcs|Case)\s*:\s*(.+?)\s*$", line)
        if m:
            out[m.group(1).lower()] = m.group(2).strip('"')
    return out


def log_tail_time(path: str, max_bytes: int = 200_000) -> float | None:
    """ログ末尾から最後の `Time = <t>` を拾う（最終計算時刻）。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            tail = f.read().decode(errors="replace")
    except OSError:
        return None
    ms = re.findall(rf"(?m)^Time = ({_NUM})s?\s*$", tail)
    return float(ms[-1]) if ms else None


# --------------------------------------------------------------------------- #
# forceCoeffs .dat ヘッダ（OpenFOAM が実際に使った magUInf/dragDir/Aref を持つ）
# --------------------------------------------------------------------------- #
def force_coeffs_header(path: str) -> dict:
    out: dict = {}
    try:
        with open(path, errors="replace") as f:
            for line in f:
                if not line.startswith("#"):
                    break
                m = re.match(r"#\s*(\w+)\s*:\s*(.+)$", line.strip())
                if not m:
                    continue
                k, v = m.group(1), m.group(2)
                vec = vector(v)
                if vec is not None:
                    out[k] = vec
                else:
                    try:
                        out[k] = float(v)
                    except ValueError:
                        out[k] = v
    except OSError:
        pass
    return out


def mesh_counts(owner_path: str) -> dict:
    """polyMesh/owner ヘッダの note "nPoints:.. nCells:.. nFaces:.." を読む（バイナリでもヘッダは ASCII）。"""
    try:
        with open(owner_path, "rb") as f:
            head = f.read(4096).decode(errors="replace")
    except OSError:
        return {}
    out = {}
    for k in ("nPoints", "nCells", "nFaces", "nInternalFaces"):
        m = re.search(rf"{k}:\s*(\d+)", head)
        if m:
            out[k] = int(m.group(1))
    return out
