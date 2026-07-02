#!/usr/bin/env bash
# 02_launch_instance.sh — Ubuntu インスタンスを起動（ホスト側で実行）
# Apple Silicon では Multipass が自動で arm64 パッケージを選ぶ（ネイティブ性能）。
set -euo pipefail

INSTANCE="${INSTANCE:-openfoam}"
# OpenFOAM 13 は Ubuntu 22.04/24.04/25.04 向けにパッケージ提供。LTS の 24.04(noble) を既定にする。
UBUNTU="${UBUNTU:-24.04}"

# --- リソース割当: ホスト用に最低 2 スレッド & 4GB を残す（Multipass 推奨）---
# M4 のコア/メモリを確認（手動で上書きしたい場合は CPUS/MEM/DISK を環境変数で指定）。
TOTAL_CPU=$(sysctl -n hw.physicalcpu 2>/dev/null || echo 8)
TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo $((16*1024*1024*1024)))
TOTAL_MEM_GB=$(( TOTAL_MEM_BYTES / 1024 / 1024 / 1024 ))

CPUS="${CPUS:-$(( TOTAL_CPU > 4 ? TOTAL_CPU - 2 : TOTAL_CPU ))}"
MEM_GB="${MEM_GB:-$(( TOTAL_MEM_GB > 8 ? TOTAL_MEM_GB - 4 : 4 ))}"
DISK="${DISK:-100}"

echo "==> インスタンス起動: name=$INSTANCE ubuntu=$UBUNTU cpus=$CPUS mem=${MEM_GB}G disk=${DISK}G"

if multipass info "$INSTANCE" >/dev/null 2>&1; then
  echo "インスタンス $INSTANCE は既に存在します。起動を確認します。"
  multipass start "$INSTANCE" || true
else
  multipass launch -c "$CPUS" -m "${MEM_GB}G" -d "${DISK}G" -n "$INSTANCE" "$UBUNTU"
fi

multipass list
echo "完了。次は scripts/03_install_openfoam13.sh"
