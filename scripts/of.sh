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
# 鍵は multipassd の鍵のコピー（sudo cp "/var/root/Library/Application Support/multipassd/ssh-keys/id_rsa"）
if [[ -z "${MP_KEY:-}" ]]; then
  MP_KEY="$HOME/.ssh/multipass_openfoam"
  [[ -f "$MP_KEY" ]] || MP_KEY=/tmp/mp_key   # 旧来の置き場所（Mac 再起動で消える）
fi
VM_IP="${VM_IP:-}"

if [[ -z "$CMD" ]]; then
  echo "usage: scripts/of.sh \"<openfoam command(s)>\"" >&2
  exit 2
fi

WORKDIR="$VM_PATH"
[[ -n "$CASE" ]] && WORKDIR="$VM_PATH/$CASE"

_run() {
  local cmd="source /opt/openfoam13/etc/bashrc && cd '$WORKDIR' && ($CMD)"
  # 経路は接続確認だけで決める（コマンド自体の失敗で別経路から再実行しない）
  if multipass exec "$INSTANCE" -- true >/dev/null 2>&1; then
    multipass exec "$INSTANCE" -- bash -lc "$cmd"
    return
  fi
  # VM IP を自動取得
  if [[ -z "$VM_IP" ]]; then
    VM_IP=$(multipass list --format csv 2>/dev/null | awk -F',' "\$1==\"$INSTANCE\"{print \$3}" | tr -d ' ')
  fi
  if [[ -z "$VM_IP" || "$VM_IP" == "--" ]]; then
    echo "ERROR: VM IP not found" >&2; return 1
  fi
  if [[ ! -f "$MP_KEY" ]]; then
    echo "ERROR: multipass exec が使えず、SSH 鍵もありません: $MP_KEY" >&2; return 1
  fi
  echo "of.sh: multipass exec 不可のため SSH 経由 ($VM_IP)" >&2
  # ConnectionAttempts: 接続確立だけを再試行（コマンドは再実行しない）。ホスト側ネットワークの瞬断対策
  # 長時間の foamRun は切断で止まるので `nohup ... > log.foamRun 2>&1 &` で VM 内に切り離して実行すること
  ssh -i "$MP_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ConnectionAttempts=6 \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
      ubuntu@"$VM_IP" "bash -lc $(printf '%q' "$cmd")"
}

_run
