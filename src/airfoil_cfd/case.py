"""ケース生成と掃引のオーケストレーション(ホスト側)。

OpenFOAM 本体は VM 内で動くため、ここでは
- テンプレ複製と辞書の値差し替え(迎角=流入Uの回転, U, 乱流プリセット)
- of.sh 経由のメッシュ/計算の起動
- 迎角の連続掃引(前段の収束解を初期場に引き継ぐ)
を担う薄い制御層を提供する。
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = os.path.join(REPO, "cases", "template")


def of(cmd: str, case_rel: str) -> subprocess.CompletedProcess:
    """scripts/of.sh 経由で VM 内 OpenFOAM コマンドを実行。case_rel はリポジトリ相対。"""
    of_sh = os.path.join(REPO, "scripts", "of.sh")
    env = dict(os.environ, CASE=case_rel)
    return subprocess.run(["bash", of_sh, cmd], env=env, check=False)


def clone_case(name: str, stl_src: str | None = None) -> str:
    """template を cases/runs/<name> に複製。0.orig -> 0 もコピー。

    stl_src: コピーする STL のパス(省略時はテンプレの STL をそのまま使う)。
    """
    dst = os.path.join(REPO, "cases", "runs", name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(TEMPLATE, dst)
    src0 = os.path.join(dst, "0.orig")
    if os.path.isdir(src0):
        shutil.copytree(src0, os.path.join(dst, "0"), dirs_exist_ok=True)
    if stl_src:
        trisurface = os.path.join(dst, "constant", "triSurface")
        os.makedirs(trisurface, exist_ok=True)
        shutil.copy2(stl_src, os.path.join(trisurface, "airfoil.stl"))
    return dst


def set_inlet_velocity(case_dir: str, u_inf: float, alpha_deg: float,
                       chord: float = 1.0, span: float = 0.01):
    """0/U の inlet を (U cosα, U sinα, 0) に書き換え、forceCoeffs も更新。"""
    a = math.radians(alpha_deg)
    ux, uy = u_inf * math.cos(a), u_inf * math.sin(a)
    upath = os.path.join(case_dir, "0", "U")
    txt = open(upath).read()
    txt = re.sub(r"uniform \([^)]*\)", f"uniform ({ux:.6f} {uy:.6f} 0)", txt, count=2)
    open(upath, "w").write(txt)

    # forceCoeffs: magUInf と Aref を実際の条件に合わせる
    fc_path = os.path.join(case_dir, "system", "forceCoeffs")
    if os.path.exists(fc_path):
        fc = open(fc_path).read()
        fc = re.sub(r"magUInf\s+[\d.eE+\-]+;", f"magUInf         {u_inf};", fc)
        fc = re.sub(r"Aref\s+[\d.eE+\-]+;", f"Aref            {chord * span};", fc)
        open(fc_path, "w").write(fc)


def set_turbulence(case_dir: str, turb: str):
    """constant/momentumTransport をプリセット(presets/momentumTransport.<RAS|LES>)で差替。"""
    preset = os.path.join(TEMPLATE, "presets", f"momentumTransport.{turb.upper()}")
    dst = os.path.join(case_dir, "constant", "momentumTransport")
    if os.path.exists(preset):
        shutil.copyfile(preset, dst)


def _fix_frontandback_to_empty(case_dir: str):
    """snappyHexMesh 後に polyMesh/boundary の frontAndBack を wall→empty に変換。

    snappyHexMesh は empty パッチを拒否するため blockMeshDict では wall を使い、
    ソルバー実行前にここで empty へ書き換える。
    """
    bpath = os.path.join(case_dir, "constant", "polyMesh", "boundary")
    if not os.path.exists(bpath):
        return
    txt = open(bpath).read()
    # frontAndBack ブロック内の type wall を type empty に変換
    import re as _re
    txt = _re.sub(
        r"(frontAndBack\s*\{[^}]*?)type\s+wall;",
        r"\1type            empty;",
        txt, flags=_re.DOTALL)
    open(bpath, "w").write(txt)


def mesh(case_rel: str):
    of("blockMesh && surfaceFeatures && snappyHexMesh -overwrite && checkMesh", case_rel)
    # snappyHexMesh 後に 2D の empty パッチを復元
    case_dir = os.path.join(REPO, case_rel)
    _fix_frontandback_to_empty(case_dir)


def run(case_rel: str, parallel_np: int = 0):
    if parallel_np > 1:
        of(f"decomposePar -force && mpirun -np {parallel_np} foamRun -parallel && reconstructPar",
           case_rel)
    else:
        of("foamRun", case_rel)


# --------------------------------------------------------------------------- #
# 迎角の連続掃引(ヒステリシス)
# --------------------------------------------------------------------------- #
def _parse_range(spec: str):
    """'0:18:1' -> [0,1,...,18] / '18:0:1' -> [18,...,0]"""
    lo, hi, step = (float(x) for x in spec.split(":"))
    n = int(abs(hi - lo) / step) + 1
    sgn = 1 if hi >= lo else -1
    return [lo + sgn * step * i for i in range(n)]


def continuous_sweep(base: str, alpha_up: str, alpha_down: str, u_inf: float,
                     turb: str = "rans", parallel_np: int = 0):
    """昇順→降順の連続掃引。前段の最終時刻場を次段の初期場に引き継ぐ。

    戻り値: [(direction, alpha, case_rel), ...]（Cl/Cd は postprocess で集計）。
    """
    results = []
    prev_dir = None
    sequence = [("up", a) for a in _parse_range(alpha_up)] + \
               [("down", a) for a in _parse_range(alpha_down)]

    for k, (direction, alpha) in enumerate(sequence):
        name = f"{base}_{direction}_a{alpha:g}"
        case_rel = os.path.join("cases", "runs", name)
        cdir = clone_case(name)
        set_turbulence(cdir, turb)
        set_inlet_velocity(cdir, u_inf, alpha)

        if prev_dir is not None:
            # 前段の最終時刻ディレクトリを mapFields で初期場に流用
            of(f"mapFields ../../../{prev_dir} -consistent -sourceTime latestTime", case_rel)

        if k == 0:
            mesh(case_rel)          # メッシュは初回のみ生成、以降は流用してもよい
        run(case_rel, parallel_np)
        results.append((direction, alpha, case_rel))
        prev_dir = case_rel
    return results
