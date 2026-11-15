"""
NACA0012 ヒステリシス掃引オーケストレーター
============================================
使い方:
  uv run python scripts/run_sweep.py           # 全掃引
  uv run python scripts/run_sweep.py --resume  # 途中から再開

手法:
  各 α の収束解を次の α の初期条件にすることでヒステリシスを再現。
  メッシュは naca0012_a8 (k-ω SST, Re=2e6, Aref=0.01) を共有。
  ボディ軸 forceCoeffs → 後処理で風軸 Cl/Cd に変換。

生成物:
  cases/runs/sweep_rans_kw/{dir}_a{alpha:02d}/  ... 各ケースディレクトリ
  docs/figures/sweep_results.csv               ... 掃引結果 (α, Cl_wind, Cd_wind)
"""

import os
import sys
import math
import shutil
import subprocess
import time
import csv
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────────────────────────────
U_INF  = 30.0           # 主流速度 [m/s]
NU     = 1.5e-5         # 動粘性 [m²/s]  → Re = 2e6
CHORD  = 1.0            # 翼弦長 [m]
SPAN   = 0.01           # 2D スパン [m]
ALPHA_UP   = list(range(0, 20, 2))     # [0, 2, ..., 18]°
ALPHA_DOWN = list(range(16, -2, -2))   # [16, 14, ..., 0]°  (18 は up の最終から初期化)

VM_IP  = "192.168.2.9"
VM_KEY = "/tmp/mp_key"
SSH    = ["ssh", "-i", VM_KEY, "-o", "StrictHostKeyChecking=no", f"ubuntu@{VM_IP}"]
OF_ENV = "source /opt/openfoam13/etc/bashrc"

VM_BASE_MESH = "/home/ubuntu/airfoil-cfd/cases/runs/naca0012_a8/constant/polyMesh"
VM_SWEEP_DIR = "/home/ubuntu/airfoil-cfd/cases/runs/sweep_rans_kw"
LOCAL_SWEEP  = Path("cases/runs/sweep_rans_kw")
RESULTS_CSV  = Path("docs/figures/sweep_results.csv")

END_TIME     = 600      # 最大反復数
WRITE_EVERY  = 300      # フィールド書き出し間隔
PURGE_WRITE  = 2        # 保持する書き出し数

# ── ユーティリティ ────────────────────────────────────────────────────────────
def vm(cmd, timeout=3600):
    """VM で OF 環境込みのコマンドを実行"""
    result = subprocess.run(
        SSH + [f"{OF_ENV} && {cmd}"],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        print(f"  [VM ERROR] {result.stderr[-500:]}")
    return result

def case_name(alpha, direction):
    return f"{direction}_a{int(round(alpha)):02d}"

def case_dir(alpha, direction):
    return LOCAL_SWEEP / case_name(alpha, direction)

def vm_case_dir(alpha, direction):
    return f"{VM_SWEEP_DIR}/{case_name(alpha, direction)}"

# ── OpenFOAM 辞書生成 ─────────────────────────────────────────────────────────
def _header(cls, obj):
    return (
        f'FoamFile {{ version 2.0; format ascii; class {cls}; object {obj}; }}\n'
    )

def write_U(path: Path, alpha_deg: float):
    alpha = math.radians(alpha_deg)
    Ux = U_INF * math.cos(alpha)
    Uy = U_INF * math.sin(alpha)
    path.write_text(
        _header("volVectorField", "U") +
        f"dimensions [0 1 -1 0 0 0 0];\n"
        f"internalField uniform ({Ux:.6f} {Uy:.6f} 0);\n"
        f"boundaryField\n{{\n"
        f"    inlet   {{ type fixedValue; value uniform ({Ux:.6f} {Uy:.6f} 0); }}\n"
        f"    outlet  {{ type inletOutlet; inletValue uniform (0 0 0); value uniform ({Ux:.6f} {Uy:.6f} 0); }}\n"
        f"    top     {{ type slip; }}\n"
        f"    bottom  {{ type slip; }}\n"
        f"    airfoil {{ type noSlip; }}\n"
        f"    frontAndBack {{ type empty; }}\n"
        f"}}\n"
    )

def write_scalar_field(path: Path, name: str, dims: str, val: float,
                       inlet_bc: str, airfoil_bc: str):
    path.write_text(
        _header("volScalarField", name) +
        f"dimensions {dims};\n"
        f"internalField uniform {val};\n"
        f"boundaryField\n{{\n"
        f"    inlet   {{ {inlet_bc} }}\n"
        f"    outlet  {{ type inletOutlet; inletValue uniform {val}; value uniform {val}; }}\n"
        f"    top     {{ type slip; }}\n"
        f"    bottom  {{ type slip; }}\n"
        f"    airfoil {{ {airfoil_bc} }}\n"
        f"    frontAndBack {{ type empty; }}\n"
        f"}}\n"
    )

def write_0_fields(d: Path, alpha_deg: float):
    """初期条件フィールド生成（Spalart-Allmaras）"""
    d.mkdir(parents=True, exist_ok=True)
    write_U(d / "U", alpha_deg)

    # SA: nuTilda = 3 × ν (フリーストリーム、低乱流度)
    nu_tilda = 3 * NU
    write_scalar_field(d / "p", "p", "[0 2 -2 0 0 0 0]", 0.0,
                       "type zeroGradient;", "type zeroGradient;")
    write_scalar_field(d / "nuTilda", "nuTilda", "[0 2 -1 0 0 0 0]", nu_tilda,
                       f"type fixedValue; value uniform {nu_tilda};",
                       "type fixedValue; value uniform 0;")   # 壁面で nuTilda=0
    write_scalar_field(d / "nut", "nut", "[0 2 -1 0 0 0 0]", 0.0,
                       "type calculated; value uniform 0;",
                       "type nutUSpaldingWallFunction; value uniform 0;")

def write_physical_properties(path: Path):
    path.write_text(
        _header("dictionary", "physicalProperties") +
        f"viscosityModel  constant;\n"
        f"nu              [0 2 -1 0 0 0 0] {NU};\n"
    )

def write_momentum_transport(path: Path):
    path.write_text(
        _header("dictionary", "momentumTransport") +
        "simulationType  RAS;\n"
        "RAS { model SpalartAllmaras; turbulence on; printCoeffs on; }\n"
    )

def write_control_dict(path: Path):
    path.write_text(
        _header("dictionary", "controlDict") +
        f"solver          incompressibleFluid;\n"
        f"startFrom       latestTime;\n"
        f"startTime       0;\n"
        f"stopAt          endTime;\n"
        f"endTime         {END_TIME};\n"
        f"deltaT          1;\n"
        f"writeControl    timeStep;\n"
        f"writeInterval   {WRITE_EVERY};\n"
        f"purgeWrite      {PURGE_WRITE};\n"
        f"writeFormat     binary;\n"
        f"writePrecision  8;\n"
        f"writeCompression off;\n"
        f"runTimeModifiable yes;\n"
        f"functions\n{{\n"
        f"    #includeFunc forceCoeffs\n"
        f"}}\n"
    )

def write_fv_schemes(path: Path):
    path.write_text(
        _header("dictionary", "fvSchemes") +
        "ddtSchemes      { default steadyState; }\n"
        "gradSchemes     { default Gauss linear; grad(U) cellLimited Gauss linear 1; }\n"
        "divSchemes\n{\n"
        "    default            none;\n"
        "    div(phi,U)         bounded Gauss linearUpwind grad(U);\n"
        "    div(phi,nuTilda)   bounded Gauss upwind;\n"  # SA
        "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        "}\n"
        "laplacianSchemes { default Gauss linear limited corrected 0.5; }\n"  # limited で非直交対策
        "interpolationSchemes { default linear; }\n"
        "snGradSchemes   { default limited corrected 0.5; }\n"  # 非直交対策
        "wallDist        { method meshWave; }\n"
    )

def write_fv_solution(path: Path):
    path.write_text(
        _header("dictionary", "fvSolution") +
        "solvers\n{\n"
        "    p\n    { solver GAMG; smoother GaussSeidel;"
        " tolerance 1e-7; relTol 0.01; }\n"
        "    \"(U|nuTilda|nut)\"\n"             # SA 変数
        "    { solver smoothSolver; smoother symGaussSeidel;"
        " tolerance 1e-8; relTol 0.05; }\n"
        "}\n"
        "SIMPLE\n{\n"
        "    nNonOrthogonalCorrectors 3;\n"     # 非直交86°対策（1→3）
        "    consistent      yes;\n"
        "    residualControl { p 1e-4; U 1e-4; nuTilda 1e-4; }\n"
        "}\n"
        "relaxationFactors\n{\n"
        "    fields    { p 0.3; }\n"
        "    equations { U 0.7; nuTilda 0.7; }\n"  # SA は k-ω より緩和できる
        "}\n"
    )

def write_force_coeffs(path: Path):
    path.write_text(
        "type            forceCoeffs;\n"
        "libs            (\"libforces.so\");\n"
        "writeControl    timeStep;\n"
        "writeInterval   1;\n"
        "log             yes;\n"
        "patches         (airfoil);\n"
        "rho             rhoInf;\n"
        "rhoInf          1.0;\n"
        "liftDir         (0 1 0);\n"   # ボディ軸固定 → 後処理で風軸に回転
        "dragDir         (1 0 0);\n"
        "CofR            (0.25 0 0);\n"
        "pitchAxis       (0 0 1);\n"
        f"magUInf         {U_INF};\n"
        f"lRef            {CHORD};\n"
        f"Aref            {CHORD * SPAN};\n"
    )

# ── ケースセットアップ ─────────────────────────────────────────────────────────
def setup_case(alpha, direction, prev_vm_case=None):
    """ケースディレクトリを作成し、前ステップ解を初期条件としてコピー"""
    cdir = case_dir(alpha, direction)
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "constant").mkdir(exist_ok=True)
    (cdir / "system").mkdir(exist_ok=True)

    write_physical_properties(cdir / "constant" / "physicalProperties")
    write_momentum_transport(cdir / "constant" / "momentumTransport")
    write_control_dict(cdir / "system" / "controlDict")
    write_fv_schemes(cdir / "system" / "fvSchemes")
    write_fv_solution(cdir / "system" / "fvSolution")
    write_force_coeffs(cdir / "system" / "forceCoeffs")

    # メッシュをコピー（VM 上で実行）
    vm_cdir = vm_case_dir(alpha, direction)
    print(f"  メッシュコピー: {VM_BASE_MESH} → {vm_cdir}/constant/polyMesh")
    vm(f"mkdir -p {vm_cdir}/constant && "
       f"cp -r {VM_BASE_MESH} {vm_cdir}/constant/polyMesh")

    if prev_vm_case is None:
        # 最初のケース: テンプレート初期条件を書き込む
        write_0_fields(cdir / "0", alpha)
        print(f"  初期条件: テンプレートから生成 (U方向 α={alpha}°)")
    else:
        # 前ステップの最終時刻場をコピー → U の inlet だけ更新
        print(f"  初期条件: {prev_vm_case} の最終時刻場をコピー")
        vm(
            f"LAST=$(foamListTimes -case {prev_vm_case} | tail -1) && "
            f"echo \"前ステップ最終時刻: $LAST\" && "
            f"mkdir -p {vm_cdir}/0 && "
            f"cp -r {prev_vm_case}/$LAST/. {vm_cdir}/0/ && "
            f"rm -rf {vm_cdir}/0/uniform"   # time メタデータ除去 (開始時刻を 0 に保つ)
        )
        # U の inlet 速度を更新 (ローカルで 0/U を上書き)
        write_U(cdir / "0" / "U", alpha)
    return vm_cdir

# ── forceCoeffs 解析 ──────────────────────────────────────────────────────────
def last_cl_cd_body(vm_cdir: str):
    """VM の forceCoeffs.dat からボディ軸 Cl/Cd を取得（最後の有効行）"""
    fc_path = f"{vm_cdir}/postProcessing/forceCoeffs/0/forceCoeffs.dat"
    result = vm(f"tail -200 {fc_path}")
    if result.returncode != 0:
        return None, None
    rows = []
    for line in result.stdout.splitlines():
        if line.strip().startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                vals = [float(p) for p in parts[:4]]
                if not any(math.isnan(v) for v in vals):
                    rows.append(vals)
            except ValueError:
                pass
    if not rows:
        return None, None
    # 最後の ~50 行の平均（収束後の値）
    recent = rows[-min(50, len(rows)):]
    avg = [sum(x[i] for x in recent) / len(recent) for i in range(4)]
    # forceCoeffs の列: Time Cm Cd Cl
    Cd_body, Cl_body = avg[2], avg[3]
    return Cl_body, Cd_body

def body_to_wind(Cl_body, Cd_body, alpha_deg):
    """ボディ軸 → 風軸変換"""
    a = math.radians(alpha_deg)
    Cl_wind = Cl_body * math.cos(a) - Cd_body * math.sin(a)
    Cd_wind = Cd_body * math.cos(a) + Cl_body * math.sin(a)
    return Cl_wind, Cd_wind

# ── メインループ ──────────────────────────────────────────────────────────────
def run_alpha(alpha, direction, prev_vm_case=None):
    name = case_name(alpha, direction)
    print(f"\n{'='*60}")
    print(f"  α = {alpha:3.0f}°  {'昇順' if direction == 'up' else '降順'}  ({name})")
    print(f"{'='*60}")

    vm_cdir = setup_case(alpha, direction, prev_vm_case)

    # foamRun をバックグラウンドで起動し、NaN 検知で早期終了
    t0 = time.time()
    print(f"  foamRun 実行中 ...", flush=True)
    vm(f"cd {vm_cdir} && nohup foamRun > foamRun.log 2>&1 & echo $! > foamRun.pid")

    # ポーリング: 30 秒ごとにログを確認
    converged = False
    diverged  = False
    for _ in range(240):   # 最大 120 分
        time.sleep(30)
        status = vm(f"tail -40 {vm_cdir}/foamRun.log")
        log = status.stdout

        # プロセス完了チェック
        pid_r = vm(f"cat {vm_cdir}/foamRun.pid 2>/dev/null")
        pid = pid_r.stdout.strip()
        running = vm(f"kill -0 {pid} 2>/dev/null && echo yes || echo no").stdout.strip() == "yes" if pid else False

        # NaN 検知
        if "nan" in log.lower() or "nan" in log:
            print(f"  ! NaN 検知 → foamRun 強制終了")
            if pid:
                vm(f"kill {pid} 2>/dev/null || true")
            diverged = True
            break

        # 収束検知 (residualControl が達成されると foamRun が終了)
        if not running:
            converged = "End" in log or "SIMPLE solution converged" in log
            break

        # 進捗表示
        elapsed = (time.time() - t0) / 60
        last_time = ""
        for line in reversed(log.splitlines()):
            if line.startswith("Time ="):
                last_time = line.strip()
                break
        print(f"  {elapsed:.0f}分経過  {last_time}", flush=True)

    elapsed = time.time() - t0
    state = "収束" if converged else ("発散(NaN)" if diverged else "タイムアウト/終了")
    print(f"  状態: {state}  ({elapsed/60:.1f} 分)")

    Cl_b, Cd_b = last_cl_cd_body(vm_cdir)
    if Cl_b is None:
        print(f"  forceCoeffs 読み取り失敗")
        return vm_cdir, None, None

    Cl_w, Cd_w = body_to_wind(Cl_b, Cd_b, alpha)
    print(f"  ボディ軸: Cl={Cl_b:.4f}  Cd={Cd_b:.4f}")
    print(f"  風軸:     Cl={Cl_w:.4f}  Cd={Cd_w:.4f}")
    return vm_cdir, Cl_w, Cd_w

def main():
    resume = "--resume" in sys.argv

    LOCAL_SWEEP.mkdir(parents=True, exist_ok=True)
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)

    # VM 側の sweep ディレクトリを作成
    vm(f"mkdir -p {VM_SWEEP_DIR}")

    results = []

    # 既存 CSV を読み込んで resume 対応
    done_keys = set()
    if resume and RESULTS_CSV.exists():
        with open(RESULTS_CSV) as f:
            for row in csv.DictReader(f):
                done_keys.add((float(row["alpha"]), row["direction"]))
        print(f"再開: {len(done_keys)} ステップ完了済み")

    prev_case = None

    def record(alpha, direction, Cl, Cd):
        results.append({"alpha": alpha, "direction": direction, "Cl": Cl, "Cd": Cd})
        with open(RESULTS_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["alpha", "direction", "Cl", "Cd"])
            w.writeheader()
            w.writerows(results)

    # ── 昇順掃引 ─────────────────────────────────────────────────────────────
    print("\n\n【昇順掃引 0°→18°】")
    for alpha in ALPHA_UP:
        key = (float(alpha), "up")
        if resume and key in done_keys:
            print(f"  skip: α={alpha}° up (完了済み)")
            prev_case = vm_case_dir(alpha, "up")
            continue
        vm_cdir, Cl, Cd = run_alpha(alpha, "up", prev_case)
        if Cl is not None:
            record(alpha, "up", Cl, Cd)
        prev_case = vm_cdir

    # ── 降順掃引 ─────────────────────────────────────────────────────────────
    print("\n\n【降順掃引 16°→0°】")
    # 最初の降順ケース(α=16°)は昇順の α=18° 解から始める
    prev_case = vm_case_dir(18, "up")

    for alpha in ALPHA_DOWN:
        key = (float(alpha), "dn")
        if resume and key in done_keys:
            print(f"  skip: α={alpha}° dn (完了済み)")
            prev_case = vm_case_dir(alpha, "dn")
            continue
        vm_cdir, Cl, Cd = run_alpha(alpha, "dn", prev_case)
        if Cl is not None:
            record(alpha, "dn", Cl, Cd)
        prev_case = vm_cdir

    print(f"\n\n掃引完了。結果: {RESULTS_CSV}")
    print(f"プロット: uv run python scripts/plot_hysteresis.py")

if __name__ == "__main__":
    main()
