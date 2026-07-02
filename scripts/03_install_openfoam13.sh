#!/usr/bin/env bash
# 03_install_openfoam13.sh — VM 内に OpenFOAM 13 を導入（ホストから multipass exec で実行）
# 参考: https://openfoam.org/download/13-ubuntu/
set -euo pipefail

INSTANCE="${INSTANCE:-openfoam}"

echo "==> VM '$INSTANCE' に OpenFOAM 13 を導入します"

# dl.openfoam.org のリポジトリを登録して apt 導入。VM 内で一括実行する。
multipass exec "$INSTANCE" -- bash -lc '
  set -euo pipefail
  sudo apt-get update
  sudo apt-get install -y wget software-properties-common ca-certificates gnupg

  # OpenFOAM Foundation の apt リポジトリを追加
  wget -qO - https://dl.openfoam.org/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/openfoam-archive-keyring.gpg
  sudo add-apt-repository -y "deb [signed-by=/usr/share/keyrings/openfoam-archive-keyring.gpg] http://dl.openfoam.org/ubuntu $(lsb_release -cs) main" || \
    sudo add-apt-repository -y http://dl.openfoam.org/ubuntu

  sudo apt-get update
  sudo apt-get install -y openfoam13

  # 環境設定を ~/.bashrc に追加（冪等）
  grep -q "openfoam13/etc/bashrc" ~/.bashrc || \
    echo "source /opt/openfoam13/etc/bashrc" >> ~/.bashrc
'

echo "==> 動作確認（foamRun のヘルプが出れば成功）"
multipass exec "$INSTANCE" -- bash -lc 'source /opt/openfoam13/etc/bashrc && foamRun -help | head -n 5 && echo "---" && which foamRun && blockMesh -help >/dev/null && echo blockMesh_OK'

echo "完了。次は scripts/04_mount_project.sh"
