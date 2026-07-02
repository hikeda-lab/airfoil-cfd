#!/usr/bin/env bash
# of.sh — VM 内で OpenFOAM コマンドを実行するラッパー（ホスト側 / Claude Code から使う）
#
# 使い方:
#   scripts/of.sh "blockMesh && snappyHexMesh -overwrite && foamRun"
#   CASE=cases/runs/naca0012_a8 scripts/of.sh "foamRun"
#   NP=6 scripts/of.sh "decomposePar && mpirun -np $NP foamRun -parallel && reconstructPar"
#
# 環境変数:
#   INSTANCE  VM 名 (既定: openfoam)
#   VM_PATH   VM 内のリポジトリルート (既定: /home/ubuntu/airfoil-cfd)
#   CASE      リポジトリルートからの相対ケースパス（指定時はそこに cd して実行）
set -euo pipefail

INSTANCE="${INSTANCE:-openfoam}"
VM_PATH="${VM_PATH:-/home/ubuntu/airfoil-cfd}"
CASE="${CASE:-}"
CMD="${*:-}"
# multipass exec が "No route to host" になる場合の SSH フォールバック
MP_KEY="${MP_KEY:-/tmp/mp_key}"
VM_IP="${VM_IP:-}"

if [[ -z "$CMD" ]]; then
  echo "usage: scripts/of.sh \"<openfoam command(s)>\"" >&2
  exit 2
fi

WORKDIR="$VM_PATH"
[[ -n "$CASE" ]] && WORKDIR="$VM_PATH/$CASE"

_run() {
  local cmd="source /opt/openfoam13/etc/bashrc && cd '$WORKDIR' && ($CMD)"
  # multipass exec を試み、失敗したら直接 SSH にフォールバック
  if multipass exec "$INSTANCE" -- bash -lc "$cmd" 2>/dev/null; then
    return 0
  fi
  # VM IP を自動取得
  if [[ -z "$VM_IP" ]]; then
    VM_IP=$(multipass list --format csv 2>/dev/null | awk -F',' "\$1==\"$INSTANCE\"{print \$3}" | tr -d ' ')
  fi
  if [[ -z "$VM_IP" || "$VM_IP" == "--" ]]; then
    echo "ERROR: VM IP not found" >&2; return 1
  fi
  ssh -i "$MP_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
      ubuntu@"$VM_IP" "bash -lc $(printf '%q' "$cmd")"
}

_run
