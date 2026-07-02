#!/usr/bin/env bash
# NACA0012 α スイープ — VM 内で逐次実行するスクリプト
# 使い方: nohup bash run_sweep.sh > sweep.log 2>&1 &
# OpenFOAM の bashrc は bash -lc 経由で呼ぶ（直接 source すると shell 変数コンテキストエラー）

BASE="/home/ubuntu/naca0012_incomp_a8"
SWEEP="/home/ubuntu/naca0012_sweep"
U_INF=30.0
ANGLES="0 2 4 6 8 10 12 14 16 18 20"

mkdir -p "$SWEEP"

RESULT_CSV="$SWEEP/polar.csv"
echo "alpha,Cl,Cd,Cm" > "$RESULT_CSV"

for alpha in $ANGLES; do
    CASE="$SWEEP/alpha_$(printf '%02d' $alpha)"
    echo "============================================"
    echo "=== alpha = ${alpha} deg  @ $(date +'%H:%M:%S') ==="
    echo "============================================"

    # ── ケースディレクトリを準備 ────────────────────────────
    rm -rf "$CASE"
    mkdir -p "$CASE"
    cp -r "$BASE/constant" "$CASE/"
    cp -r "$BASE/system"   "$CASE/"
    cp -r "$BASE/0"        "$CASE/"
    find "$CASE" -mindepth 2 -name "[0-9]*" -type d -exec rm -rf {} + 2>/dev/null || true
    rm -rf "$CASE/postProcessing"

    # ── 設定ファイルを Python で生成 ────────────────────────
    python3 - "$alpha" "$U_INF" "$CASE" << 'PYEOF'
import sys, math

alpha = float(sys.argv[1])
U     = float(sys.argv[2])
case  = sys.argv[3]

a  = math.radians(alpha)
Ux = U * math.cos(a)
Uz = U * math.sin(a)
ca = math.cos(a)
sa = math.sin(a)

open(f"{case}/0/U", "w").write(f"""\
FoamFile {{ format ascii; class volVectorField; object U; }}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({Ux:.6f} 0 {Uz:.6f});
boundaryField
{{
    freestream
    {{
        type            freestreamVelocity;
        freestreamValue uniform ({Ux:.6f} 0 {Uz:.6f});
        value           uniform ({Ux:.6f} 0 {Uz:.6f});
    }}
    wall
    {{
        type            noSlip;
    }}
    #includeEtc "caseDicts/setConstraintTypes"
}}
""")

open(f"{case}/system/controlDict", "w").write(f"""\
FoamFile {{ format ascii; class dictionary; object controlDict; }}
solver          incompressibleFluid;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         3000;
deltaT          1;
writeControl    timeStep;
writeInterval   300;
purgeWrite      3;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    forceCoeffs
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        writeControl    timeStep;
        writeInterval   1;
        log             yes;
        patches         (aerofoil);
        rho             rhoInf;
        rhoInf          1.0;
        dragDir         ( {ca:.8f}  0  {sa:.8f});
        liftDir         (-{sa:.8f}  0  {ca:.8f});
        CofR            (0.25 0 0);
        pitchAxis       (0 1 0);
        magUInf         {U:.1f};
        lRef            1.0;
        Aref            1.0;
    }}
}}
""")
PYEOF

    # ── foamRun 実行（bash -lc で OF 環境を読み込む）───────
    bash -lc "source /opt/openfoam13/etc/bashrc && cd '$CASE' && foamRun" \
        > "$CASE/log.foamRun" 2>&1
    echo "foamRun finished for alpha=${alpha} @ $(date +'%H:%M:%S')"

    # ── 最終 Cl/Cd 抽出 ─────────────────────────────────────
    DAT="$CASE/postProcessing/forceCoeffs/0/forceCoeffs.dat"
    if [[ -f "$DAT" ]]; then
        LAST=$(tail -2 "$DAT" | head -1)
        Cm=$(echo "$LAST" | awk '{print $2}')
        Cd=$(echo "$LAST" | awk '{print $3}')
        Cl=$(echo "$LAST" | awk '{print $4}')
        echo "  => Cl=${Cl}  Cd=${Cd}  Cm=${Cm}"
        echo "${alpha},${Cl},${Cd},${Cm}" >> "$RESULT_CSV"
    else
        echo "WARNING: no forceCoeffs.dat for alpha=${alpha}"
        echo "${alpha},NaN,NaN,NaN" >> "$RESULT_CSV"
    fi
done

echo ""
echo "=== ALL SWEEPS COMPLETE @ $(date +'%H:%M:%S') ==="
cat "$RESULT_CSV"
