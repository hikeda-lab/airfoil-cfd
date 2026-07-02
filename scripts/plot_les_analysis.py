"""
LES post-processing: vorticity (wake-focused) + Cl-t history
"""
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.font_manager as fm
from pathlib import Path

fm.fontManager.addfont("/Users/hajime/Library/Fonts/NotoSansCJKjp-Regular.otf")
plt.rcParams["font.family"] = "Noto Sans CJK JP"

FIGDIR = Path("docs/figures")
FIGDIR.mkdir(parents=True, exist_ok=True)

try:
    import pyvista as pv
except ImportError:
    sys.exit("pyvista not installed")

# ── 1. forceCoeffs 時間履歴 ────────────────────────────────────────────
dat = Path("docs/figures/les_forceCoeffs.dat")
rows = []
for line in dat.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    parts = line.split()
    if len(parts) >= 4:
        try:
            rows.append([float(p) for p in parts[:4]])
        except ValueError:
            pass

data = np.array(rows)
t_fc   = data[:, 0]
Cm_fc  = data[:, 1]
Cd_fc  = data[:, 2]
Cl_fc  = data[:, 3]

# ── 2. VTK 読み込み（スナップショット t≈36ms）────────────────────────
vtk_file = Path("docs/figures/naca0012_les_a14_78000.vtk")
print(f"Reading {vtk_file} ...")
mesh = pv.read(vtk_file)
print(f"  Arrays: {mesh.array_names}")

# ── 3. スパン中央断面のスライス ────────────────────────────────────────
slice_mid = mesh.slice(normal="y", origin=(0, -0.25, 0))

pts = np.array(slice_mid.points)
x_s, z_s = pts[:, 0], pts[:, 2]

def get_field(slc, name):
    if name in slc.point_data:
        return np.array(slc.point_data[name])
    if name in slc.cell_data:
        slc2 = slc.cell_data_to_point_data()
        return np.array(slc2.point_data.get(name, np.zeros(len(pts))))
    return None

vort = get_field(slice_mid, "vorticity")
p_arr = get_field(slice_mid, "p")
U_arr = get_field(slice_mid, "U")

# ── 4. プロット ────────────────────────────────────────────────────────
fig = plt.figure(figsize=(16, 10))
gs = gridspec.GridSpec(2, 3, figure=fig, wspace=0.38, hspace=0.4)

# ─ 4a. Cl(t) ─────────────────────────────────────────────────────────
ax_cl = fig.add_subplot(gs[0, :2])
ax_cl.plot(t_fc * 1000, Cl_fc, color="royalblue", lw=1.0, label="LES Cl (WALE)")
ax_cl.axhline(1.340, ls="--", color="tomato", lw=1.5, label="RANS Cl=1.34")
ax_cl.set_xlabel("t  [ms]")
ax_cl.set_ylabel("Cl")
ax_cl.set_title("揚力係数 Cl の時間履歴  (NACA0012 α=14° LES)")
ax_cl.legend(fontsize=9)
ax_cl.grid(True, ls="--", alpha=0.5)

# ─ 4b. Cd(t) ─────────────────────────────────────────────────────────
ax_cd = fig.add_subplot(gs[0, 2])
ax_cd.plot(t_fc * 1000, Cd_fc, color="darkorange", lw=1.0)
ax_cd.axhline(0.0268, ls="--", color="tomato", lw=1.5, label="RANS Cd=0.027")
ax_cd.set_xlabel("t  [ms]")
ax_cd.set_ylabel("Cd")
ax_cd.set_title("抗力係数 Cd の時間履歴")
ax_cd.legend(fontsize=9)
ax_cd.grid(True, ls="--", alpha=0.5)

# ─ 4c. Ωy  後流域にズームイン（スケール制限） ──────────────────────────
ax_wy = fig.add_subplot(gs[1, 0])
if vort is not None:
    omega_y = vort[:, 1]
    # 後流域のみ
    mask = (x_s >= -0.1) & (x_s <= 1.6) & (z_s >= -0.35) & (z_s <= 0.35)
    clip_val = 800.0   # 1/s — 近壁極値を除外してスケール固定
    lvls_y = np.linspace(-clip_val, clip_val, 51)
    sc = ax_wy.tricontourf(x_s[mask], z_s[mask], omega_y[mask],
                            levels=lvls_y, cmap="RdBu_r", extend="both")
    plt.colorbar(sc, ax=ax_wy, shrink=0.85, label="Ωy [1/s]")
ax_wy.set_xlim(-0.1, 1.6); ax_wy.set_ylim(-0.35, 0.35)
ax_wy.set_xlabel("x/c"); ax_wy.set_ylabel("z/c")
ax_wy.set_title("スパン渦度 Ωy  スパン中央断面  t=100ms")
ax_wy.set_aspect("equal"); ax_wy.grid(True, ls="--", alpha=0.3)

# ─ 4d. Ωx (streamwise vorticity — 3D signature) ───────────────────────
ax_wx = fig.add_subplot(gs[1, 1])
if vort is not None:
    omega_x = vort[:, 0]
    clip_x = 15.0
    lvls_x = np.linspace(-clip_x, clip_x, 51)
    sc2 = ax_wx.tricontourf(x_s[mask], z_s[mask], omega_x[mask],
                             levels=lvls_x, cmap="RdBu_r", extend="both")
    plt.colorbar(sc2, ax=ax_wx, shrink=0.85, label="Ωx [1/s]")
ax_wx.set_xlim(-0.1, 1.6); ax_wx.set_ylim(-0.35, 0.35)
ax_wx.set_xlabel("x/c"); ax_wx.set_ylabel("z/c")
ax_wx.set_title("流れ方向渦度 Ωx — 3次元渦構造")
ax_wx.set_aspect("equal"); ax_wx.grid(True, ls="--", alpha=0.3)

# ─ 4e. 圧力 ─────────────────────────────────────────────────────────
ax_p = fig.add_subplot(gs[1, 2])
if p_arr is not None:
    vmax_p = 500.0
    lvls_p = np.linspace(-vmax_p, vmax_p, 51)
    sc3 = ax_p.tricontourf(x_s[mask], z_s[mask], p_arr[mask],
                            levels=lvls_p, cmap="coolwarm", extend="both")
    plt.colorbar(sc3, ax=ax_p, shrink=0.85, label="p [m²/s²]")
ax_p.set_xlim(-0.1, 1.6); ax_p.set_ylim(-0.35, 0.35)
ax_p.set_xlabel("x/c"); ax_p.set_ylabel("z/c")
ax_p.set_title("圧力場 p  スパン中央断面")
ax_p.set_aspect("equal"); ax_p.grid(True, ls="--", alpha=0.3)

fig.suptitle("NACA0012  LES WALE  α=14°  Re=2e6  (t=100ms, 流れ場通過 3.0 回)",
             fontsize=12, y=1.01)

out = FIGDIR / "naca0012_les_analysis.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"\nSaved: {out}")

# ── 5. Cl/Cd 統計 ─────────────────────────────────────────────────────
t_start = 0.01   # 初期過渡を除く
mask_t = t_fc >= t_start
if mask_t.sum() > 10:
    print(f"\n--- Force stats (t >= {t_start*1000:.0f}ms) ---")
    print(f"  Cl: mean={Cl_fc[mask_t].mean():.3f}, std={Cl_fc[mask_t].std():.4f}, "
          f"min={Cl_fc[mask_t].min():.3f}, max={Cl_fc[mask_t].max():.3f}")
    print(f"  Cd: mean={Cd_fc[mask_t].mean():.4f}, std={Cd_fc[mask_t].std():.5f}")
