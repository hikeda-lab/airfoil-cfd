"""有限スパン翼(NACA4412、翼端渦フィージビリティ)の可視化: Q基準等値面 + 翼端付近の断面速度場。"""
import numpy as np
import pyvista as pv

VTK = "cases/runs/naca4412_finitespan_test/VTK/naca4412_finitespan_test_11398.vtk"
AIRFOIL_VTK = "cases/runs/naca4412_finitespan_test/VTK/airfoil/airfoil_11398.vtk"

mesh = pv.read(VTK)
mesh = mesh.compute_derivative(scalars="U", gradient=True, vorticity=True)
g = mesh["gradient"].reshape(-1, 3, 3)
S = 0.5 * (g + g.transpose(0, 2, 1))
Omega = 0.5 * (g - g.transpose(0, 2, 1))
q = 0.5 * (np.einsum("nij,nij->n", Omega, Omega) - np.einsum("nij,nij->n", S, S))
mesh["Q"] = q
mesh["velMag"] = np.linalg.norm(mesh["U"], axis=1)
mesh["omega_x"] = mesh["vorticity"][:, 0]   # 流れ方向(X)まわりの渦度 = 翼端(縦)渦の指標

# 後流(翼面境界層を除く x>0.95)のみに絞って翼端渦コアを抽出
wake_region = mesh.clip_box((0.95, 4.0, -1.5, 1.5, 0.5, 2.0), invert=False)

iso_val = 3000.0
contour = wake_region.contour(isosurfaces=[iso_val], scalars="Q")
print(f"Q iso value: {iso_val:.2f}, n points on iso: {contour.n_points}")

pl = pv.Plotter(off_screen=True, window_size=(1600, 1000))
pl.add_mesh(mesh.clip_box((-1, 6, -3, 3, 0, 3), invert=False), color="lightgray", opacity=0.04)
if contour.n_points > 0:
    pl.add_mesh(contour, scalars="velMag", cmap="turbo", show_scalar_bar=True)
pl.add_mesh(pv.read(AIRFOIL_VTK), color="dimgray")
pl.camera_position = [(4.5, -3.5, 3.0), (1.5, 0.0, 1.0), (0, 0, 1)]
pl.add_axes()
pl.screenshot("docs/figures/naca4412_finitespan_tipvortex_Q_t04.png")
print("saved docs/figures/naca4412_finitespan_tipvortex_Q_t04.png")

# 翼端後方のY-Z断面(流れ方向Xに垂直)での流れ方向渦度omega_x。
for x_pos in (1.05, 1.3, 1.8, 2.5):
    sl = mesh.slice(normal=(1, 0, 0), origin=(x_pos, 0, 0))
    sl = sl.clip_box((x_pos - 0.01, x_pos + 0.01, -1.0, 1.0, 0.3, 2.0), invert=False)
    pl2 = pv.Plotter(off_screen=True, window_size=(1000, 900))
    pl2.add_mesh(sl, scalars="omega_x", cmap="RdBu_r", show_scalar_bar=True, clim=[-30, 30])
    pl2.camera_position = "yz"
    pl2.add_axes()
    fname = f"docs/figures/naca4412_finitespan_tipvortex_slice_x{x_pos:.2f}_t04.png"
    pl2.screenshot(fname)
    print(f"saved {fname}")
