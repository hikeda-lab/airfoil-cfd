"""後処理: Cl/Cd 収束・時間平均、Cp 分布、3D 渦可視化(Q/λ2/渦度)。

OpenFOAM の postProcessing 出力をホスト側で読み、図を docs/figures/ に保存する。
"""
from __future__ import annotations

import glob
import os

import numpy as np


# --------------------------------------------------------------------------- #
# Cl / Cd (forceCoeffs)
# --------------------------------------------------------------------------- #
def read_force_coeffs(case: str, aref_override: float | None = None,
                      lref_override: float | None = None):
    """postProcessing/forceCoeffs/<t>/*.dat を読み (time, Cd, Cl, Cm) を返す。

    ヘッダの Aref/lRef を解析し、override 指定があれば正規化を再スケールする。
    OpenFOAM の列順が不定なためヘッダ行の列名で解決する。
    """
    cands = sorted(glob.glob(os.path.join(case, "postProcessing", "forceCoeffs*", "*", "*.dat")))
    if not cands:
        raise FileNotFoundError(f"forceCoeffs 出力が見つかりません: {case}")
    path = cands[-1]
    cols, rows = None, []
    aref_file = lref_file = None
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                hdr = line.lstrip("#").split()
                if any(c.lower() in ("cd", "cl", "cm") for c in hdr):
                    cols = hdr
                # parse Aref/lRef from header comments
                if "Aref" in line and ":" in line:
                    try:
                        aref_file = float(line.split(":")[-1].strip())
                    except ValueError:
                        pass
                if "lRef" in line and ":" in line:
                    try:
                        lref_file = float(line.split(":")[-1].strip())
                    except ValueError:
                        pass
                continue
            vals = [float(x) for x in line.split()]
            if vals:
                rows.append(vals)
    data = np.array(rows)
    idx = {name.lower(): i for i, name in enumerate(cols)} if cols else {}
    t = data[:, 0]
    cd = data[:, idx.get("cd", 1)]
    cl = data[:, idx.get("cl", 2)]
    cm = data[:, idx.get("cm", 3)] if data.shape[1] > 3 else np.full_like(t, np.nan)

    # Cl_correct = Cl_file × (Aref_file / Aref_correct)
    # because Cl_file = F / (q × Aref_file), Cl_correct = F / (q × Aref_correct)
    aref_scale = (aref_file / aref_override) if (aref_override and aref_file) else 1.0
    lref_scale = (lref_file / lref_override) if (lref_override and lref_file) else 1.0
    cd = cd * aref_scale
    cl = cl * aref_scale
    cm = cm * aref_scale * lref_scale
    return t, cd, cl, cm


def force_summary(case: str, transient: bool = False, settle_frac: float = 0.5,
                  aref: float | None = None, lref: float | None = None):
    """定常は末尾値、非定常(LES)は後半の時間平均±rms を返す。"""
    t, cd, cl, cm = read_force_coeffs(case, aref_override=aref, lref_override=lref)
    if transient:
        i0 = int(len(t) * settle_frac)
        return {"Cl": float(cl[i0:].mean()), "Cl_rms": float(cl[i0:].std()),
                "Cd": float(cd[i0:].mean()), "Cd_rms": float(cd[i0:].std())}
    return {"Cl": float(cl[-1]), "Cd": float(cd[-1]), "Cm": float(cm[-1])}


def wind_axis(fx: float, fy: float, alpha_deg: float):
    """翼固定軸の力(Fx,Fy)を迎角 α で風軸の (Drag, Lift) に回す。"""
    a = np.radians(alpha_deg)
    drag = fx * np.cos(a) + fy * np.sin(a)
    lift = fy * np.cos(a) - fx * np.sin(a)
    return drag, lift


# --------------------------------------------------------------------------- #
# Cp 分布
# --------------------------------------------------------------------------- #
def cp_from_surface(case: str, u_inf: float, p_inf: float = 0.0):
    """surfaces で出した壁面 p から Cp = (p - p∞)/(0.5 U²) を計算。

    .raw 形式 (x y z p) または .xy 形式 (#x y z p) を自動判別。
    最新時刻ファイルを使用。戻り値: (x_over_c, cp)。
    """
    patterns = [
        os.path.join(case, "postProcessing", "surfaces", "*", "*.raw"),
        os.path.join(case, "postProcessing", "surfaces", "*", "*.xy"),
        os.path.join(case, "postProcessing", "*", "*", "*airfoil*.raw"),
        os.path.join(case, "postProcessing", "*", "*", "*airfoil*.xy"),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    files = sorted(set(files))
    if not files:
        raise FileNotFoundError("壁面 p のサンプリングが見つかりません (.raw/.xy)")
    arr = np.loadtxt(files[-1], comments="#")
    x, p = arr[:, 0], arr[:, -1]
    chord = x.max() - x.min()
    cp = (p - p_inf) / (0.5 * u_inf**2)
    # x/c をソートして上下面を分離（x 昇順: 下面が先に来る場合がある）
    order = np.argsort(x)
    return (x[order] - x.min()) / chord, cp[order]


def plot_cp(case: str, u_inf: float, out: str, alpha_deg: float = 0.0,
            airfoil: str = ""):
    import matplotlib.pyplot as plt
    xc, cp = cp_from_surface(case, u_inf)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(xc, cp, s=10, c="steelblue", linewidths=0)
    ax.invert_yaxis()
    ax.set_xlabel("x/c"); ax.set_ylabel("Cp")
    title = f"Surface Cp  (U={u_inf:.1f} m/s"
    if alpha_deg:
        title += f", α={alpha_deg}°"
    if airfoil:
        title += f", {airfoil}"
    title += ")"
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_convergence(case: str, out: str,
                     aref: float | None = None, lref: float | None = None):
    """Cl/Cd 収束履歴を PNG に保存する。"""
    import matplotlib.pyplot as plt
    t, cd, cl, _ = read_force_coeffs(case, aref_override=aref, lref_override=lref)
    fig, axes = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
    axes[0].plot(t, cl, "b-", lw=1)
    axes[0].set_ylabel("Cl"); axes[0].grid(True, alpha=0.3)
    axes[1].plot(t, cd, "r-", lw=1)
    axes[1].set_ylabel("Cd"); axes[1].set_xlabel("Iteration")
    axes[1].grid(True, alpha=0.3)
    fig.suptitle(f"Force coefficient convergence  (final Cl={cl[-1]:.4f}, Cd={cd[-1]:.4f})")
    fig.tight_layout()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 3D 渦可視化 (pyvista)
# --------------------------------------------------------------------------- #
def visualize_vortex(case: str, method: str = "q", iso: float = 50.0, out: str = "vortex.png"):
    """foamToVTK 済みの結果 or .foam を読み、Q/λ2/渦度の等値面を保存する。

    事前に VM で `scripts/of.sh "foamToVTK -latestTime"` を実行しておくこと。
    """
    import pyvista as pv

    vtk_files = sorted(glob.glob(os.path.join(case, "VTK", "*.vtk"))
                       + glob.glob(os.path.join(case, "VTK", "**", "*.vtu"), recursive=True))
    if not vtk_files:
        raise FileNotFoundError("VTK が無い。先に foamToVTK を実行してください。")
    mesh = pv.read(vtk_files[-1])

    if method in ("q", "lambda2"):
        mesh = mesh.compute_derivative(scalars="U", gradient=True)
        # Q 基準 / λ2 は勾配テンソルから算出（簡易: Q = -0.5 tr(gradU^2) 相当の近似）
        g = mesh["gradient"].reshape(-1, 3, 3)
        S = 0.5 * (g + g.transpose(0, 2, 1))
        Omega = 0.5 * (g - g.transpose(0, 2, 1))
        q = 0.5 * (np.einsum("nij,nij->n", Omega, Omega)
                   - np.einsum("nij,nij->n", S, S))
        mesh["Q"] = q
        contour = mesh.contour(isosurfaces=[iso], scalars="Q")
    else:  # vorticity
        mesh = mesh.compute_derivative(scalars="U", vorticity=True)
        mesh["vortMag"] = np.linalg.norm(mesh["vorticity"], axis=1)
        contour = mesh.contour(isosurfaces=[iso], scalars="vortMag")

    pl = pv.Plotter(off_screen=True)
    pl.add_mesh(contour, scalars="U" if "U" in contour.array_names else None, cmap="viridis")
    pl.add_axes()
    pl.screenshot(out)
    return out
