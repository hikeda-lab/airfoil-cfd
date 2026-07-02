"""
LES 3D vorticity visualization for NACA0012 α=14°
Reads VTK file, plots mid-span vorticity (Ωy) and Q-criterion slices.
"""
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.font_manager as fm
from pathlib import Path

fm.fontManager.addfont("/Users/hajime/Library/Fonts/NotoSansCJKjp-Regular.otf")
plt.rcParams["font.family"] = "Noto Sans CJK JP"

VTK_FILE = Path("docs/figures/naca0012_les_a14_26000.vtk")
FIGDIR = Path("docs/figures")
FIGDIR.mkdir(parents=True, exist_ok=True)

try:
    import pyvista as pv
except ImportError:
    sys.exit("pyvista not installed. Run: uv add pyvista vtk")

pv.set_plot_theme("document")

print(f"Reading {VTK_FILE} ...")
mesh = pv.read(VTK_FILE)
print(f"  Cells: {mesh.n_cells}, Points: {mesh.n_points}")
print(f"  Arrays: {mesh.array_names}")
print(f"  Bounds: {mesh.bounds}")

# ── 渦度場の処理 ──────────────────────────────────────────────────────
if "vorticity" in mesh.array_names:
    vort = mesh.point_data["vorticity"] if "vorticity" in mesh.point_data else mesh.cell_data["vorticity"]
    # Ωy = vorticity[:, 1] (スパン方向成分 → 2D渦巻きを示す)
    omega_y = vort[:, 1]
    # Ωx, Ωz (縦渦・スパン方向渦構造)
    omega_x = vort[:, 0]
    omega_z = vort[:, 2]
    omega_mag = np.linalg.norm(vort, axis=1)
else:
    print("WARNING: vorticity not found, computing from U gradient")
    omega_y = None

# ── スパン中央断面（y ≈ -0.25m）でスライス ────────────────────────────
print("Slicing at mid-span y=-0.25 ...")
slice_mid = mesh.slice(normal="y", origin=(0, -0.25, 0))

# ── 翼端付近断面（y ≈ -0.05m）でスライス ──────────────────────────────
slice_tip = mesh.slice(normal="y", origin=(0, -0.05, 0))

# ── プロット ───────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("NACA0012 LES α=14°  —  3D 渦構造  (t ≈ 36ms)", fontsize=13, y=1.01)

def plot_slice_scalar(ax, slice_data, field, title, cmap="RdBu_r", sym=True, vmax=None):
    pts = np.array(slice_data.points)
    if field in slice_data.point_data:
        vals = np.array(slice_data.point_data[field])
    elif field in slice_data.cell_data:
        sdata2 = slice_data.cell_data_to_point_data()
        vals = np.array(sdata2.point_data.get(field, np.zeros(len(pts))))
    else:
        vals = np.zeros(len(pts))

    # x-z 平面にプロット（y成分を無視）
    x, z = pts[:, 0], pts[:, 2]
    if vmax is None:
        vmax = np.percentile(np.abs(vals), 95) if sym else np.percentile(vals, 95)
    vmin = -vmax if sym else 0

    sc = ax.tricontourf(x, z, vals, levels=50, cmap=cmap, vmin=vmin, vmax=vmax)
    plt.colorbar(sc, ax=ax, shrink=0.8, label=field)
    ax.set_xlim(-0.5, 1.5)
    ax.set_ylim(-0.3, 0.3)
    ax.set_xlabel("x/c")
    ax.set_ylabel("z/c")
    ax.set_title(title)
    ax.set_aspect("equal")
    ax.grid(True, ls="--", alpha=0.3)

# スパン中央: Ωy（2D揚力面渦）
if "vorticity" in slice_mid.point_data:
    vort_mid = np.array(slice_mid.point_data["vorticity"])
    omega_y_mid = vort_mid[:, 1]
    pts_mid = np.array(slice_mid.points)
    x_m, z_m = pts_mid[:, 0], pts_mid[:, 2]
    vmax_oy = np.percentile(np.abs(omega_y_mid), 95)
    sc1 = axes[0, 0].tricontourf(x_m, z_m, omega_y_mid, levels=50,
                                   cmap="RdBu_r", vmin=-vmax_oy, vmax=vmax_oy)
    plt.colorbar(sc1, ax=axes[0, 0], shrink=0.8, label="Ωy [1/s]")
    axes[0, 0].set_title("スパン中央断面 (y=-0.25m)  ─  Ωy (スパン渦度)")
    axes[0, 0].set_xlim(-0.5, 1.5); axes[0, 0].set_ylim(-0.3, 0.3)
    axes[0, 0].set_xlabel("x/c"); axes[0, 0].set_ylabel("z/c")
    axes[0, 0].set_aspect("equal"); axes[0, 0].grid(True, ls="--", alpha=0.3)

    # スパン中央: |Ω| (渦度マグニチュード)
    omega_mag_mid = np.linalg.norm(vort_mid, axis=1)
    vmax_om = np.percentile(omega_mag_mid, 95)
    sc2 = axes[0, 1].tricontourf(x_m, z_m, omega_mag_mid, levels=50,
                                   cmap="hot_r", vmin=0, vmax=vmax_om)
    plt.colorbar(sc2, ax=axes[0, 1], shrink=0.8, label="|Ω| [1/s]")
    axes[0, 1].set_title("スパン中央断面  ─  |Ω| 渦度マグニチュード")
    axes[0, 1].set_xlim(-0.5, 1.5); axes[0, 1].set_ylim(-0.3, 0.3)
    axes[0, 1].set_xlabel("x/c"); axes[0, 1].set_ylabel("z/c")
    axes[0, 1].set_aspect("equal"); axes[0, 1].grid(True, ls="--", alpha=0.3)

    # 翼端付近: Ωx (縦渦を見る)
    if "vorticity" in slice_tip.point_data:
        vort_tip = np.array(slice_tip.point_data["vorticity"])
        omega_x_tip = vort_tip[:, 0]
        pts_tip = np.array(slice_tip.points)
        x_t, z_t = pts_tip[:, 0], pts_tip[:, 2]
        vmax_ox = np.percentile(np.abs(omega_x_tip), 95)
        sc3 = axes[1, 0].tricontourf(x_t, z_t, omega_x_tip, levels=50,
                                      cmap="RdBu_r", vmin=-vmax_ox, vmax=vmax_ox)
        plt.colorbar(sc3, ax=axes[1, 0], shrink=0.8, label="Ωx [1/s]")
        axes[1, 0].set_title("翼端付近 (y=-0.05m)  ─  Ωx (流れ方向渦度)")
        axes[1, 0].set_xlim(-0.5, 1.5); axes[1, 0].set_ylim(-0.3, 0.3)
        axes[1, 0].set_xlabel("x/c"); axes[1, 0].set_ylabel("z/c")
        axes[1, 0].set_aspect("equal"); axes[1, 0].grid(True, ls="--", alpha=0.3)

# 圧力場
if "p" in slice_mid.point_data:
    p_mid = np.array(slice_mid.point_data["p"])
    vmax_p = np.percentile(np.abs(p_mid), 95)
    sc4 = axes[1, 1].tricontourf(x_m, z_m, p_mid, levels=50,
                                   cmap="coolwarm", vmin=-vmax_p, vmax=vmax_p)
    plt.colorbar(sc4, ax=axes[1, 1], shrink=0.8, label="p [m²/s²]")
    axes[1, 1].set_title("スパン中央断面  ─  圧力場 p")
    axes[1, 1].set_xlim(-0.5, 1.5); axes[1, 1].set_ylim(-0.3, 0.3)
    axes[1, 1].set_xlabel("x/c"); axes[1, 1].set_ylabel("z/c")
    axes[1, 1].set_aspect("equal"); axes[1, 1].grid(True, ls="--", alpha=0.3)

plt.tight_layout()
out = FIGDIR / "naca0012_les_vorticity.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"\nSaved: {out}")
plt.show()
