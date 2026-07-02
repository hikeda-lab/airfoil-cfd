"""
NACA0012 LES Post-processing Suite
===================================
Usage:
  uv run python scripts/les_postprocess.py

Generates:
  docs/figures/les_forces.png        — Cl/Cd/Cm 時間履歴 + 統計
  docs/figures/les_vorticity_t47.png — t=0.47s スパン渦度・圧力スナップショット
  docs/figures/les_q3d_t47.png       — t=0.47s Q値スライス + Ωx 3次元渦構造

VM側での事前作業（1回のみ）:
  foamPostProcess -func vorticity
  foamPostProcess -func Q
  foamToVTK -fields "(U p vorticity Q UMean pMean UPrime2Mean)"
"""
import sys
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.font_manager as fm
from pathlib import Path

fm.fontManager.addfont("/Users/hajime/Library/Fonts/NotoSansCJKjp-Regular.otf")
plt.rcParams["font.family"] = "Noto Sans CJK JP"

try:
    import pyvista as pv
except ImportError:
    sys.exit("pyvista not installed: uv add pyvista vtk")

FIGDIR = Path("docs/figures")
FIGDIR.mkdir(parents=True, exist_ok=True)

ALPHA   = 14.0
U_INF   = 30.0
CHORD   = 1.0
FLOW_THROUGH = CHORD / U_INF   # ≈ 0.0333 s

# ══════════════════════════════════════════════════════════════════════════════
# 1.  forceCoeffs 時間履歴
# ══════════════════════════════════════════════════════════════════════════════
def load_forcecoeffs(path: Path) -> np.ndarray:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                rows.append([float(p) for p in parts[:4]])
            except ValueError:
                pass
    return np.array(rows)   # [t, Cm, Cd, Cl]

fc_file = FIGDIR / "les_forceCoeffs.dat"
if not fc_file.exists():
    sys.exit(f"forceCoeffs.dat not found at {fc_file}\n"
             "Copy from VM: scp ubuntu@<VM>:/home/ubuntu/naca0012_les_a14/"
             "postProcessing/forceCoeffs/0/forceCoeffs.dat docs/figures/les_forceCoeffs.dat")

data = load_forcecoeffs(fc_file)
t, Cm, Cd, Cl = data[:, 0], data[:, 1], data[:, 2], data[:, 3]
ft = t / FLOW_THROUGH   # 流れ場通過回数

# 統計（発達後: 3通過時間以降）
mask_stat = t >= 6 * FLOW_THROUGH   # 6回通過以降（初期過渡除外）
Cl_mean, Cl_std = Cl[mask_stat].mean(), Cl[mask_stat].std()
Cd_mean, Cd_std = Cd[mask_stat].mean(), Cd[mask_stat].std()
print(f"[統計 t≥{6*FLOW_THROUGH*1000:.0f}ms]  Cl={Cl_mean:.3f}±{Cl_std:.3f}  "
      f"Cd={Cd_mean:.4f}±{Cd_std:.4f}")

fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
axes[0].plot(ft, Cl, lw=0.7, color="royalblue", label="LES WALE")
axes[0].axhline(1.340, ls="--", color="tomato", lw=1.5, label="RANS k-ω SST")
axes[0].axhline(Cl_mean, ls=":", color="royalblue", lw=1.5,
                label=f"LES 平均 {Cl_mean:.3f}±{Cl_std:.3f}")
axes[0].fill_between(ft, Cl_mean - Cl_std, Cl_mean + Cl_std,
                     alpha=0.15, color="royalblue")
axes[0].set_ylabel("Cl"); axes[0].legend(fontsize=8)
axes[0].set_title("NACA0012 α=14°  LES WALE  Re=2e6 — 空力係数時間履歴")
axes[0].grid(True, ls="--", alpha=0.4)

axes[1].plot(ft, Cd, lw=0.7, color="darkorange")
axes[1].axhline(0.0268, ls="--", color="tomato", lw=1.5, label="RANS Cd=0.027")
axes[1].axhline(Cd_mean, ls=":", color="darkorange", lw=1.5,
                label=f"LES 平均 {Cd_mean:.4f}±{Cd_std:.4f}")
axes[1].set_ylabel("Cd"); axes[1].legend(fontsize=8)
axes[1].grid(True, ls="--", alpha=0.4)

axes[2].plot(ft, Cm, lw=0.7, color="seagreen")
axes[2].axhline(0, ls="--", color="gray", lw=0.8)
axes[2].set_ylabel("Cm"); axes[2].set_xlabel("t / T_flow (流れ場通過回数)")
axes[2].grid(True, ls="--", alpha=0.4)

fig.tight_layout()
out = FIGDIR / "les_forces.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved: {out}")
plt.close(fig)

# ══════════════════════════════════════════════════════════════════════════════
# 2.  スナップショット可視化（VTKファイルから）
# ══════════════════════════════════════════════════════════════════════════════
vtk_latest = FIGDIR / "naca0012_les_a14_98000.vtk"   # t≈0.47s
if not vtk_latest.exists():
    print(f"\n{vtk_latest} not found — skipping field plots")
    sys.exit(0)

print(f"\nReading {vtk_latest} ...")
mesh = pv.read(vtk_latest)
print(f"  Points: {mesh.n_points},  Arrays: {[a for a in mesh.array_names if mesh.array_names.count(a)==1]}")

def get_pd(slc, name):
    """point_data / cell_data から配列取得"""
    if name in slc.point_data:
        return np.array(slc.point_data[name])
    if name in slc.cell_data:
        return np.array(slc.cell_data_to_point_data().point_data.get(name, []))
    return None

def contourf_clipped(ax, x, z, val, levels_n, cmap, clip, label, sym=True):
    vmin = -clip if sym else 0
    lvls = np.linspace(vmin, clip, levels_n + 1)
    sc = ax.tricontourf(x, z, val, levels=lvls, cmap=cmap, extend="both")
    plt.colorbar(sc, ax=ax, shrink=0.85, label=label)

# スパン中央スライス（y = -0.25 m）
slc = mesh.slice(normal="y", origin=(0, -0.25, 0))
pts = np.array(slc.points)
x_s, z_s = pts[:, 0], pts[:, 2]
mask = (x_s >= -0.1) & (x_s <= 1.6) & (z_s >= -0.4) & (z_s <= 0.4)

vort = get_pd(slc, "vorticity")
p_arr = get_pd(slc, "p")
Q_arr = get_pd(slc, "Q")
U_arr = get_pd(slc, "U")

# ─ Figure 2: Ωy・Ωx・p・|U| ─────────────────────────────────────────────
fig2, axes2 = plt.subplots(2, 2, figsize=(14, 9))
fig2.suptitle("NACA0012  LES WALE  α=14°  t=0.47s (流れ場通過 14.1回)", fontsize=12)

if vort is not None:
    oy = vort[:, 1];  ox = vort[:, 0]
    contourf_clipped(axes2[0, 0], x_s[mask], z_s[mask], oy[mask],
                     60, "RdBu_r", 800, "Ωy [1/s]")
    axes2[0, 0].set_title("スパン渦度 Ωy  (y=-0.25m)")

    contourf_clipped(axes2[0, 1], x_s[mask], z_s[mask], ox[mask],
                     60, "RdBu_r", 20, "Ωx [1/s]")
    axes2[0, 1].set_title("流れ方向渦度 Ωx  — 3次元縦渦")

if p_arr is not None:
    contourf_clipped(axes2[1, 0], x_s[mask], z_s[mask], p_arr[mask],
                     60, "coolwarm", 600, "p [m²/s²]")
    axes2[1, 0].set_title("圧力場 p")

if U_arr is not None:
    umag = np.linalg.norm(U_arr, axis=1)
    contourf_clipped(axes2[1, 1], x_s[mask], z_s[mask], umag[mask],
                     60, "viridis", 45, "|U| [m/s]", sym=False)
    axes2[1, 1].set_title("速度マグニチュード |U|")

for ax in axes2.flat:
    ax.set_xlim(-0.1, 1.6); ax.set_ylim(-0.4, 0.4)
    ax.set_xlabel("x/c"); ax.set_ylabel("z/c")
    ax.set_aspect("equal"); ax.grid(True, ls="--", alpha=0.3)

fig2.tight_layout()
out2 = FIGDIR / "les_vorticity_t47.png"
fig2.savefig(out2, dpi=150, bbox_inches="tight")
print(f"Saved: {out2}")
plt.close(fig2)

# ─ Figure 3: Q値スライス + Ωx（渦構造強調）─────────────────────────────
if Q_arr is not None:
    fig3, axes3 = plt.subplots(1, 2, figsize=(14, 5))
    fig3.suptitle("NACA0012  LES  t=0.47s — 渦識別: Q値 と Ωx", fontsize=12)

    q_pos = np.clip(Q_arr, 0, None)    # Q>0 が渦コア
    # 境界層の極値を除外：後流域 (x>0.1) の 95パーセンタイルでクリップ
    wake_mask = mask & (x_s > 0.1)
    q_clip = float(np.percentile(q_pos[wake_mask], 95)) if wake_mask.sum() > 0 else 1e4
    q_clip = max(q_clip, 100.0)   # 最低100 1/s²
    contourf_clipped(axes3[0], x_s[mask], z_s[mask], q_pos[mask],
                     60, "hot_r", q_clip, "Q [1/s²]", sym=False)
    axes3[0].set_title(f"Q値 (正値, clip={q_clip:.0f}) — 渦コア領域")

    if vort is not None:
        contourf_clipped(axes3[1], x_s[mask], z_s[mask], ox[mask],
                         60, "RdBu_r", 20, "Ωx [1/s]")
        axes3[1].set_title("Ωx — 反対回転縦渦ペア (3次元渦フィラメント)")

    for ax in axes3:
        ax.set_xlim(-0.1, 1.6); ax.set_ylim(-0.4, 0.4)
        ax.set_xlabel("x/c"); ax.set_ylabel("z/c")
        ax.set_aspect("equal"); ax.grid(True, ls="--", alpha=0.3)

    fig3.tight_layout()
    out3 = FIGDIR / "les_q3d_t47.png"
    fig3.savefig(out3, dpi=150, bbox_inches="tight")
    print(f"Saved: {out3}")
    plt.close(fig3)

print("\n--- 完了 ---")
