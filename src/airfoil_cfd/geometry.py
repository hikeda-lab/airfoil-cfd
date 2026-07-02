"""翼型ジオメトリ生成: NACA 4/5 桁・任意 .dat 読込・2D/3D STL 押し出し。

迎角は流入速度で与える方針のため、ここでは常に α=0 姿勢の翼を生成する。
出力 STL を snappyHexMesh の triSurface として使う。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


# --------------------------------------------------------------------------- #
# 翼型座標の生成
# --------------------------------------------------------------------------- #
def cosine_spacing(n: int) -> np.ndarray:
    """前後縁を密にするコサイン分布の x/c (0..1)。"""
    beta = np.linspace(0.0, np.pi, n)
    return 0.5 * (1.0 - np.cos(beta))


def naca4(code: str, n: int = 200, chord: float = 1.0, closed_te: bool = True):
    """NACA 4 桁翼型の (上面, 下面) 座標を返す。code 例: '2412', '0012'。"""
    m = int(code[0]) / 100.0          # 最大キャンバ
    p = int(code[1]) / 10.0           # 最大キャンバ位置
    t = int(code[2:]) / 100.0         # 最大厚み

    x = cosine_spacing(n)
    # 厚み分布 (closed_te で後縁を厳密に閉じる係数)
    a4 = -0.1015 if not closed_te else -0.1036
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2
                  + 0.2843 * x**3 + a4 * x**4)

    yc = np.where(x < p,
                  m / max(p**2, 1e-9) * (2 * p * x - x**2),
                  m / max((1 - p) ** 2, 1e-9) * ((1 - 2 * p) + 2 * p * x - x**2))
    dyc = np.where(x < p,
                   2 * m / max(p**2, 1e-9) * (p - x),
                   2 * m / max((1 - p) ** 2, 1e-9) * (p - x))
    theta = np.arctan(dyc)

    xu = x - yt * np.sin(theta)
    yu = yc + yt * np.cos(theta)
    xl = x + yt * np.sin(theta)
    yl = yc - yt * np.cos(theta)

    upper = np.column_stack([xu, yu]) * chord
    lower = np.column_stack([xl, yl]) * chord
    return upper, lower


def naca5(code: str, n: int = 200, chord: float = 1.0):
    """NACA 5 桁翼型（標準系列, 例 '23012'）。簡易実装：厚みは 4 桁式を流用。"""
    cl_des = int(code[0]) * 0.15        # 設計揚力係数の目安
    p_pos = int(code[1:3]) / 200.0      # キャンバ位置
    t = int(code[3:]) / 100.0
    # 標準 5 桁のキャンバ定数（mとk1）は p_pos に依存。代表値テーブルで近似。
    table = {0.05: (0.0580, 361.4), 0.10: (0.1260, 51.64),
             0.15: (0.2025, 15.957), 0.20: (0.2900, 6.643),
             0.25: (0.3910, 3.230)}
    key = min(table, key=lambda k: abs(k - p_pos))
    m, k1 = table[key]
    x = cosine_spacing(n)
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2
                  + 0.2843 * x**3 - 0.1036 * x**4)
    yc = np.where(x < m,
                  k1 / 6 * (x**3 - 3 * m * x**2 + m**2 * (3 - m) * x),
                  k1 * m**3 / 6 * (1 - x))
    dyc = np.gradient(yc, x)
    theta = np.arctan(dyc)
    scale = cl_des / 0.3 if cl_des else 1.0
    yc *= scale
    xu = x - yt * np.sin(theta); yu = yc + yt * np.cos(theta)
    xl = x + yt * np.sin(theta); yl = yc - yt * np.cos(theta)
    return (np.column_stack([xu, yu]) * chord,
            np.column_stack([xl, yl]) * chord)


def load_dat(path: str, chord: float = 1.0):
    """Selig 形式 .dat を読み、(上面, 下面) に分割して返す。"""
    pts = []
    with open(path) as f:
        for line in f:
            nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
            if len(nums) >= 2:
                try:
                    pts.append((float(nums[0]), float(nums[1])))
                except ValueError:
                    continue
    arr = np.array(pts)
    if arr.size == 0:
        raise ValueError(f"座標が読めません: {path}")
    # Selig は前縁(x~0)で折り返す。前縁 index で上下に分ける。
    le = int(np.argmin(arr[:, 0]))
    upper = arr[: le + 1][::-1]
    lower = arr[le:]
    return upper * chord, lower * chord


# --------------------------------------------------------------------------- #
# STL 押し出し（2D 薄板 / 3D）
# --------------------------------------------------------------------------- #
@dataclass
class ExtrudeSpec:
    mode: str = "2d"          # "2d" | "3d-infinite" | "3d-finite"
    span: float = 0.01        # スパン長 [m]（2d は薄く）
    cap_tip: bool = False     # 3d-finite で翼端を閉じるか


def _loop(upper: np.ndarray, lower: np.ndarray) -> np.ndarray:
    """上面(前縁→後縁)と下面(後縁→前縁)を結合した 1 周ループ。重複点を除去。"""
    loop = np.vstack([upper, lower[::-1]])
    keep = [0]
    for i in range(1, len(loop)):
        if np.linalg.norm(loop[i] - loop[keep[-1]]) > 1e-9:
            keep.append(i)
    return loop[keep]


def extrude_to_stl(upper, lower, spec: ExtrudeSpec, out_path: str) -> str:
    """翼型 2D ループを z 方向に押し出して STL を書き出す。"""
    from stl import mesh as stlmesh  # numpy-stl

    loop = _loop(upper, lower)
    nseg = len(loop)
    z0, z1 = 0.0, spec.span
    p0 = np.column_stack([loop, np.full(nseg, z0)])
    p1 = np.column_stack([loop, np.full(nseg, z1)])

    tris = []
    # 側面（押し出し面）
    for i in range(nseg):
        j = (i + 1) % nseg
        tris.append([p0[i], p0[j], p1[j]])
        tris.append([p0[i], p1[j], p1[i]])

    # 端面キャップ（必要時）。2D は両端 empty にするので張らない運用も可。
    def cap(points, flip):
        c = points.mean(axis=0)
        for i in range(nseg):
            j = (i + 1) % nseg
            t = [c, points[i], points[j]]
            tris.append(t[::-1] if flip else t)

    if spec.mode == "2d":
        # 2D: 両端を閉じておく（empty 境界は snappy/extrude 側で扱う）
        cap(p0, flip=True)
        cap(p1, flip=False)
    elif spec.mode == "3d-finite":
        cap(p0, flip=True)             # 翼根側を閉じる
        if spec.cap_tip:
            cap(p1, flip=False)        # 翼端を閉じる（開けると自由端）
    # 3d-infinite: 端面は周期境界のため張らない

    data = np.zeros(len(tris), dtype=stlmesh.Mesh.dtype)
    for k, tri in enumerate(tris):
        data["vectors"][k] = np.array(tri)
    m = stlmesh.Mesh(data)
    m.save(out_path)
    return out_path


def build(airfoil: str | None = None, dat: str | None = None, chord: float = 1.0,
          points: int = 200, mode: str = "2d", span: float | None = None,
          cap_tip: bool = False, out: str = "airfoil.stl") -> str:
    """高レベル API: 形状ソースを選んで STL を生成。"""
    if dat:
        upper, lower = load_dat(dat, chord)
    elif airfoil and airfoil.lower().startswith("naca"):
        code = airfoil[4:]
        upper, lower = (naca5(code, points, chord) if len(code) == 5
                        else naca4(code, points, chord))
    else:
        raise ValueError("--airfoil nacaXXXX か --dat <path> を指定してください")

    if span is None:
        span = 0.01 * chord if mode == "2d" else 3.0 * chord
    spec = ExtrudeSpec(mode=mode, span=span, cap_tip=cap_tip)
    return extrude_to_stl(upper, lower, spec, out)
