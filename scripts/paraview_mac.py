"""
Mac ParaView 6.1.1 バッチレンダリング — NACA0012 LES Q等値面
=============================================================
使い方（macOS ホスト）:
  /Applications/ParaView-6.1.1.app/Contents/bin/pvpython scripts/paraview_mac.py

  または: uv run python scripts/paraview_mac.py  （pvpython を呼び出す）

特徴:
- GPU 加速（Metal/OpenGL）で VM の Xvfb より約 40 倍高速
- docs/figures/*.vtk のローカルファイルを処理
- 全フレームを docs/figures/les_paraview_mac/ に保存

VM から VTK を追加コピーする場合:
  scp -i /tmp/mp_key ubuntu@192.168.2.9:'/home/ubuntu/naca0012_les_a14/VTK/naca0012_les_a14_*.vtk' docs/figures/vtk/
  CASE_VTK_DIR = "docs/figures/vtk"
"""

import os
import sys
import glob
import time
import subprocess

# ── 設定 ────────────────────────────────────────────────────────────────
PV_PYTHON    = "/Applications/ParaView-6.1.1.app/Contents/bin/pvpython"
CASE_VTK_DIR = "docs/figures/vtk"   # VM から転送した全 157 ファイル
OUT_DIR      = "docs/figures/les_paraview_mac"
Q_ISO_VALUE  = 2000.0
P_MIN        = -1500.0
P_MAX        =  400.0

os.makedirs(OUT_DIR, exist_ok=True)

# ── このスクリプトが pvpython から呼ばれている場合は直接実行 ──────────
if "paraview" in sys.modules or any("paraview" in p for p in sys.path):
    _RUN_AS_PV = True
else:
    _RUN_AS_PV = os.environ.get("_PVPYTHON_MODE") == "1"

if not _RUN_AS_PV:
    # macOS の python から呼ばれた場合: pvpython に再実行させる
    env = os.environ.copy()
    env["_PVPYTHON_MODE"] = "1"
    vtk_files = sorted(glob.glob(f"{CASE_VTK_DIR}/naca0012_les_a14_*.vtk"))
    print(f"Found {len(vtk_files)} local VTK files, running via pvpython ...")
    result = subprocess.run(
        [PV_PYTHON, __file__],
        env=env, cwd=os.getcwd()
    )
    sys.exit(result.returncode)

# ── 以下は pvpython 内で実行 ────────────────────────────────────────────
from paraview.simple import (
    LegacyVTKReader, Contour, Show, Hide, Delete,
    ColorBy, GetColorTransferFunction, GetOpacityTransferFunction,
    RenderAllViews, SaveScreenshot, ResetCamera,
    UpdatePipeline, CreateView, GetScalarBar,
)
import paraview.simple as pvs
pvs._DisableFirstRenderCameraReset()

vtk_files = sorted(glob.glob(f"{CASE_VTK_DIR}/naca0012_les_a14_*.vtk"))
print(f"Total VTK files: {len(vtk_files)}")
if not vtk_files:
    print(f"No VTK files in {CASE_VTK_DIR}")
    sys.exit(1)

# ── ビュー設定 ────────────────────────────────────────────────────────
view = CreateView("RenderView")
view.Background       = [0.05, 0.06, 0.12]
view.ViewSize         = [1920, 1080]
view.CameraPosition   = [1.8, -3.0, 0.6]
view.CameraFocalPoint = [0.6,  0.0, 0.0]
view.CameraViewUp     = [0.0,  0.0, 1.0]

# ── カラーマップ (圧力: 青=低圧渦コア / 赤=高圧) ─────────────────────
p_lut = GetColorTransferFunction("p")
p_lut.ApplyPreset("Cool to Warm", True)
p_lut.RescaleTransferFunction(P_MIN, P_MAX)

t_total = 0.0
for idx, vtk_path in enumerate(vtk_files):
    step = os.path.basename(vtk_path).replace("naca0012_les_a14_", "").replace(".vtk", "")
    out_png = os.path.join(OUT_DIR, f"les_Qiso_{step}.png")

    if os.path.exists(out_png):
        print(f"  [{idx+1}/{len(vtk_files)}] skip: {step}")
        continue

    t0 = time.time()
    reader = LegacyVTKReader(FileNames=[vtk_path])
    UpdatePipeline(proxy=reader)

    iso = Contour(Input=reader)
    iso.ContourBy    = ["POINTS", "Q"]
    iso.Isosurfaces  = [Q_ISO_VALUE]
    iso.ComputeNormals = True
    UpdatePipeline(proxy=iso)

    disp = Show(iso, view)
    ColorBy(disp, ("POINTS", "p"))
    disp.LookupTable = p_lut
    p_lut.RescaleTransferFunction(P_MIN, P_MAX)
    disp.Representation = "Surface"
    disp.Specular = 0.2; disp.Ambient = 0.3; disp.Diffuse = 0.7

    bar = GetScalarBar(p_lut, view)
    bar.Title = "p [m²/s²]"; bar.ComponentTitle = ""; bar.Visibility = 1

    view.CameraPosition   = [1.8, -3.0, 0.6]
    view.CameraFocalPoint = [0.6,  0.0, 0.0]
    view.CameraViewUp     = [0.0,  0.0, 1.0]

    RenderAllViews()
    SaveScreenshot(out_png, view, ImageResolution=[1920, 1080])

    elapsed = time.time() - t0
    t_total += elapsed
    print(f"  [{idx+1}/{len(vtk_files)}] step={step}  {elapsed:.1f}s  -> {os.path.basename(out_png)}")

    Hide(iso, view)
    Delete(iso)
    Delete(reader)

n = len(vtk_files)
print(f"\n完了: {n} フレーム  合計 {t_total:.1f}s  平均 {t_total/max(n,1):.2f}s/frame")
print(f"出力先: {os.path.abspath(OUT_DIR)}/")
