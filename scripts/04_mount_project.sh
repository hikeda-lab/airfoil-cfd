#!/usr/bin/env bash
# 04_mount_project.sh — このリポジトリを VM 内に共有マウント（ホスト側で実行）
# ホスト側 Python が書いた STL / ケースを VM からそのまま見えるようにする。
set -euo pipefail

INSTANCE="${INSTANCE:-openfoam}"
# このスクリプトの 1 つ上（リポジトリルート）を共有する
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_PATH="${VM_PATH:-/home/ubuntu/airfoil-cfd}"

echo "==> マウント: host:$REPO_ROOT  ->  $INSTANCE:$VM_PATH"

# 既存マウントがあれば貼り直す
multipass umount "$INSTANCE:$VM_PATH" 2>/dev/null || true
multipass mount "$REPO_ROOT" "$INSTANCE:$VM_PATH"

multipass info "$INSTANCE" | grep -A3 -i mounts || true
echo "VM 内のプロジェクトパス: $VM_PATH"
echo "完了。これで scripts/of.sh が使えます。"
