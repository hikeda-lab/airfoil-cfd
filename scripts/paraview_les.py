"""
ParaView Python バッチスクリプト — NACA0012 LES 渦構造可視化
=============================================================
使い方（VM上またはParaViewがある環境で）:
  pvpython scripts/paraview_les.py

  または ParaView GUI で Tools > Python Shell から実行:
    exec(open("scripts/paraview_les.py").read())

生成物:
  docs/figures/les_Qiso_t*.png  — Q等値面（Q=500）時系列
  docs/figures/les_omega_t*.png — Ωy スライス時系列

事前にVTKを生成しておくこと:
  foamToVTK -fields "(U p vorticity Q)" -case /home/ubuntu/naca0012_les_a14
"""

CASE_VTK_DIR = "/home/ubuntu/naca0012_les_a14/VTK"
OUT_DIR      = "/home/ubuntu/naca0012_les_a14/paraview_renders"
Q_ISO_VALUE  = 500.0    # Q値の等値面 [1/s²]
OMEGA_CLIP   = 800.0    # Ωy カラースケール上限 [1/s]

import os, glob
os.makedirs(OUT_DIR, exist_ok=True)

try:
    from paraview.simple import *
except ImportError:
    print("ParaView Python API not found. Run with: pvpython scripts/paraview_les.py")
    raise

# ── VTKファイル一覧（時間順） ──────────────────────────────────────────────
vtk_files = sorted(glob.glob(f"{CASE_VTK_DIR}/naca0012_les_a14_*.vtk"))
print(f"Found {len(vtk_files)} VTK files")

for vtk_path in vtk_files[::4]:   # 4ステップごとにレンダリング
    t_label = os.path.basename(vtk_path).replace("naca0012_les_a14_", "").replace(".vtk", "")
    print(f"  Rendering step {t_label} ...")

    reader = LegacyVTKReader(FileNames=[vtk_path])
    UpdatePipeline()

    # ── Q値等値面 ─────────────────────────────────────────────────────────
    contour = Contour(Input=reader)
    contour.ContourBy = ["POINTS", "Q"]
    contour.Isosurfaces = [Q_ISO_VALUE]
    contour.ComputeNormals = True
    UpdatePipeline()

    disp = Show(contour)
    disp.ColorArrayName = ["POINTS", "vorticity"]
    disp.LookupTable = GetColorTransferFunction("vorticity")
    disp.LookupTable.RGBPoints = [
        -OMEGA_CLIP, 0.0, 0.0, 1.0,
        0.0,         1.0, 1.0, 1.0,
        OMEGA_CLIP,  1.0, 0.0, 0.0,
    ]

    view = GetActiveViewOrCreate("RenderView")
    view.Background = [0.1, 0.1, 0.1]
    view.CameraPosition    = [0.5, -2.5, 0.0]
    view.CameraFocalPoint  = [0.5,  0.0, 0.0]
    view.CameraViewUp      = [0.0,  0.0, 1.0]
    view.ViewSize          = [1600, 900]
    ResetCamera()

    SaveScreenshot(f"{OUT_DIR}/les_Qiso_{t_label}.png", view,
                   ImageResolution=[1600, 900])

    Delete(disp); Delete(contour); Delete(reader)

print(f"\nRenderings saved to {OUT_DIR}/")
