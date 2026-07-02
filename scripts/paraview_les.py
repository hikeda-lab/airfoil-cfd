"""
ParaView Python バッチスクリプト — NACA0012 LES Q等値面レンダリング
================================================================
使い方（VM上）:
  pvpython --force-offscreen-rendering /home/ubuntu/airfoil-cfd/scripts/paraview_les.py

生成物（ホスト・VM共有ディレクトリ）:
  docs/figures/les_paraview/les_Qiso_<step>.png

VTK前提:
  foamToVTK -fields "(U p vorticity Q)" 済み
  /home/ubuntu/naca0012_les_a14/VTK/ に *.vtk が存在すること

物理定数:
  chord=1m, U_inf=30m/s → Q_wake ~ (U/δ)^2, δ~0.1m → O(10^4) 1/s²
  等値面 Q=2000 で後流の中規模渦構造を捕捉
  Ωy clip ±500 1/s（後流スパン渦の典型値）
"""

import os
import glob

CASE_VTK_DIR = "/home/ubuntu/naca0012_les_a14/VTK"
# 共有ディレクトリ経由でホスト側からも見える
OUT_DIR      = "/home/ubuntu/airfoil-cfd/docs/figures/les_paraview"
Q_ISO_VALUE  = 2000.0   # 等値面レベル [1/s²] — 後流渦コアを捕捉
P_MIN        = -1500.0  # 圧力カラースケール下限 [m²/s²] — 前縁吸引ピーク
P_MAX        =  400.0   # 圧力カラースケール上限 [m²/s²] — 淀み点
STEP_EVERY   = 8        # VTKファイルの間引き（157ファイル → 約20フレーム）

os.makedirs(OUT_DIR, exist_ok=True)

try:
    from paraview.simple import (
        LegacyVTKReader, Contour, Show, Hide, Delete,
        ColorBy, GetColorTransferFunction, GetOpacityTransferFunction,
        RenderAllViews, SaveScreenshot, ResetCamera,
        UpdatePipeline, CreateView, GetScalarBar,
    )
    import paraview.simple as pvs
    pvs._DisableFirstRenderCameraReset()
except ImportError:
    raise RuntimeError(
        "ParaView Python API not found.\n"
        "Run with: pvpython <this_script>  (with DISPLAY=:99 Xvfb)"
    )

# ── VTKファイル一覧 ─────────────────────────────────────────────────────
vtk_files = sorted(glob.glob(f"{CASE_VTK_DIR}/naca0012_les_a14_*.vtk"))
if not vtk_files:
    raise FileNotFoundError(f"No VTK files found in {CASE_VTK_DIR}")

selected = vtk_files[::STEP_EVERY]
print(f"Total VTK files: {len(vtk_files)}, rendering {len(selected)} "
      f"(every {STEP_EVERY}th)")

# ── レンダービュー設定 ──────────────────────────────────────────────────
view = CreateView("RenderView")
view.Background       = [0.05, 0.06, 0.12]
view.ViewSize         = [1920, 1080]
# カメラ: chord方向(X), span方向(Y), 揚力方向(Z)
# 斜め下から見上げる視点 → 翼とスパン方向の渦構造が一望できる
view.CameraPosition   = [1.8, -3.0, 0.6]
view.CameraFocalPoint = [0.6,  0.0, 0.0]
view.CameraViewUp     = [0.0,  0.0, 1.0]
view.CameraParallelProjection = 0

# ── カラーマップ設定（圧力 p: 青=低圧渦コア / 赤=高圧） ────────────────
p_lut = GetColorTransferFunction("p")
p_lut.ApplyPreset("Cool to Warm", True)
p_lut.RescaleTransferFunction(P_MIN, P_MAX)

p_pwf = GetOpacityTransferFunction("p")
p_pwf.RescaleTransferFunction(P_MIN, P_MAX)

# ── メインループ ────────────────────────────────────────────────────────
for idx, vtk_path in enumerate(selected):
    step = os.path.basename(vtk_path).replace("naca0012_les_a14_", "").replace(".vtk", "")
    out_png = os.path.join(OUT_DIR, f"les_Qiso_{step}.png")

    if os.path.exists(out_png):
        print(f"  [{idx+1:02d}/{len(selected)}] skip (exists): {os.path.basename(out_png)}")
        continue

    print(f"  [{idx+1:02d}/{len(selected)}] step={step}  Q={Q_ISO_VALUE:.0f} ...", flush=True)

    # VTK 読み込み
    reader = LegacyVTKReader(FileNames=[vtk_path])
    UpdatePipeline(proxy=reader)

    # Q等値面 (Q は POINT_DATA にある)
    iso = Contour(Input=reader)
    iso.ContourBy   = ["POINTS", "Q"]
    iso.Isosurfaces = [Q_ISO_VALUE]
    iso.ComputeNormals = True
    UpdatePipeline(proxy=iso)

    # 表示（圧力でカラーリング：渦コア=低圧=青）
    disp = Show(iso, view)
    ColorBy(disp, ("POINTS", "p"))
    disp.LookupTable    = p_lut
    # ColorBy後に固定範囲を強制（全フレーム一貫）
    p_lut.RescaleTransferFunction(P_MIN, P_MAX)
    disp.Representation = "Surface"
    disp.Specular       = 0.2
    disp.Ambient        = 0.3
    disp.Diffuse        = 0.7

    # カラーバー（凡例）
    bar = GetScalarBar(p_lut, view)
    bar.Title            = "p [m²/s²]"
    bar.ComponentTitle   = ""
    bar.Visibility       = 1
    bar.WindowLocation   = "Lower Right Corner"

    ResetCamera(view)
    # カメラ位置を再設定（ResetCameraで上書きされるため）
    view.CameraPosition   = [1.8, -3.0, 0.6]
    view.CameraFocalPoint = [0.6,  0.0, 0.0]
    view.CameraViewUp     = [0.0,  0.0, 1.0]

    RenderAllViews()
    SaveScreenshot(out_png, view, ImageResolution=[1920, 1080])
    print(f"    -> {out_png}")

    # クリーンアップ
    Hide(iso, view)
    Delete(iso)
    Delete(reader)

print(f"\n完了: {len(selected)} フレームを {OUT_DIR} に保存しました")
