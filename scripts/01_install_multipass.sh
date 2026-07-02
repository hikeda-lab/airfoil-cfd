#!/usr/bin/env bash
# 01_install_multipass.sh — macOS に Multipass を導入する（ホスト側で実行）
# 参考: https://openfoam.org/download/macos/  /  https://canonical.com/multipass/install
set -euo pipefail

echo "==> Multipass のインストール"

if command -v multipass >/dev/null 2>&1; then
  echo "multipass は既にインストール済み: $(multipass version | head -n1)"
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  echo "Homebrew 経由でインストールします..."
  brew install --cask multipass
else
  echo "Homebrew が無いため公式 pkg を使います..."
  cd "$(mktemp -d)"
  curl -JLO https://multipass.run/download/macos
  echo "管理者パスワードを求められます（インストーラ実行のため）。"
  sudo installer -pkg ./multipass*.pkg -target /
fi

echo "==> 確認"
multipass version
echo "完了。次は scripts/02_launch_instance.sh"
