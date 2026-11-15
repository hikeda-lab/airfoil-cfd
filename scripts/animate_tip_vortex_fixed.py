"""有限スパン翼端渦(準定常区間 t=0.2〜0.4s)の3Dアニメーション — 固定視点版。

カメラ・翼位置は全フレーム固定し、Q基準等値面(流速で着色)の時間変化
(渦コアの太さ・蛇行・強度の乱流的な揺らぎ)だけを見せる。
"""
import glob
import os
import re
import sys

import numpy as np
import pyvista as pv

CASE = sys.argv[1] if len(sys.argv) > 1 else "cases/runs/naca0012_finitespan_test"
CASE_NAME = os.path.basename(CASE)
VTK_DIR = f"{CASE}/VTK"
OUT_DIR = f"docs/figures/{CASE_NAME}_tipvortex_anim_fixed"
os.makedirs(OUT_DIR, exist_ok=True)

vol_files = sorted(
    glob.glob(f"{VTK_DIR}/{CASE_NAME}_*.vtk"),
    key=lambda p: int(re.search(r"_(\d+)\.vtk$", p).group(1)),
)
print(f"{len(vol_files)} volume VTK files found")

airfoil_files = sorted(
    glob.glob(f"{VTK_DIR}/airfoil/airfoil_*.vtk"),
    key=lambda p: int(re.search(r"_(\d+)\.vtk$", p).group(1)),
)
wing = pv.read(airfoil_files[-1])

Q_ISO = 3000.0
N = len(vol_files)

# 固定カメラ(周回アニメと同じ画角の中間あたりを採用)
focal = (1.5, 0.0, 1.0)
cam_pos = (4.2, -3.2, 2.8)

pl = pv.Plotter(off_screen=True, window_size=(1600, 1000))
pl.set_background("white")

for i, vf in enumerate(vol_files):
    mesh = pv.read(vf)
    mesh = mesh.compute_derivative(scalars="U", gradient=True)
    g = mesh["gradient"].reshape(-1, 3, 3)
    S = 0.5 * (g + g.transpose(0, 2, 1))
    Omega = 0.5 * (g - g.transpose(0, 2, 1))
    q = 0.5 * (np.einsum("nij,nij->n", Omega, Omega) - np.einsum("nij,nij->n", S, S))
    mesh["Q"] = q
    mesh["velMag"] = np.linalg.norm(mesh["U"], axis=1)

    wake = mesh.clip_box((0.95, 4.0, -1.5, 1.5, 0.5, 2.0), invert=False)
    contour = wake.contour(isosurfaces=[Q_ISO], scalars="Q")

    pl.clear_actors()
    pl.add_mesh(wing, color="dimgray")
    if contour.n_points > 0:
        pl.add_mesh(contour, scalars="velMag", cmap="turbo", clim=[0, 32],
                    show_scalar_bar=(i == 0), scalar_bar_args={"title": "|U| [m/s]"})

    pl.camera_position = [cam_pos, focal, (0, 0, 1)]
    pl.add_axes()

    out_png = os.path.join(OUT_DIR, f"frame_{i:03d}.png")
    pl.screenshot(out_png)
    print(f"[{i+1}/{N}] {os.path.basename(vf)} -> {out_png}")

print("done")
