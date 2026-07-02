# airfoil-cfd

Mac mini (Apple Silicon M4) 上で **Multipass + Ubuntu + OpenFOAM 13** を使い、翼型 (airfoil) の
**非圧縮・低レイノルズ数** CFD を行うための環境・スキル・ツール一式。Claude Code で運用する前提。

## できること（要件）

1. 抗力 Cd・揚力 Cl の算出と翼面圧力分布 (Cp) のプロット
2. 失速近傍の **揚力ヒステリシス** の再現検証（迎角の昇順／降順連続掃引）
3. 翼型の差し替え（NACA 4/5 桁 + 任意 `.dat`）
4. **RANS / LES** 両対応
5. **3D（スパン押し出し）** 解析と **翼端渦** の可視化
6. **空力騒音**（Curle + FFT、任意で FW-H）

## アーキテクチャ

- ホスト (macOS): Claude Code ＋ **uv** 管理の Python（ジオメトリ生成・後処理）
- ゲスト (Ubuntu VM `openfoam`, Multipass): **OpenFOAM 13** 本体（メッシュ・ソルバー）
- 両者を `multipass mount` で共有。ホストから `scripts/of.sh` で VM 内 OpenFOAM を実行。

## クイックスタート

```bash
# 0) 環境構築（ホスト）
bash scripts/01_install_multipass.sh
bash scripts/02_launch_instance.sh
bash scripts/03_install_openfoam13.sh
bash scripts/04_mount_project.sh
uv sync                      # Python 環境

# 1) 2D ベースライン（翼型差替可）
uv run afcfd geometry --airfoil naca0012 --chord 1 --mode 2d \
    --out cases/template/constant/triSurface/airfoil.stl
uv run afcfd case --name naca0012_a5 --turb rans --U 30 --alpha 5
uv run afcfd run  --name naca0012_a5 --mesh --np 6
uv run afcfd post --case naca0012_a5 --U 30 --cp --coeffs

# 2) ヒステリシス掃引
uv run afcfd sweep --case-base naca0012 --alpha-up 0:18:1 --alpha-down 18:0:1 --U 30 --turb rans

# 4) LES へ切替（同じ翼型）
uv run afcfd case --name naca0012_les --turb les --U 30 --alpha 8
#   → controlDict を非定常設定に（deltaT/endTime/adjustTimeStep/maxCo）。case-builder スキル参照

# 5) 空力騒音（LES 後）
uv run afcfd acoustics --case naca0012_les --U 30 --ref-len 1.0
```

## ドキュメント / スキル

- `CLAUDE.md` — プロジェクト指針（**OpenFOAM 13 の必須仕様**と禁止事項）
- `PLAN.md` — 6 フェーズのロードマップ
- `.claude/skills/` — Claude Code が文脈に応じて読む手順書（case-builder / geometry / turbulence / postprocess / hysteresis / aeroacoustics）

## 重要な前提・制約

- OpenFOAM 13 は **モジュラーソルバー**。`foamRun` ＋ `solver incompressibleFluid` を使い、
  `simpleFoam`/`pimpleFoam` は使わない（`CLAUDE.md` 参照）。
- **FW-H は標準 OpenFOAM に含まれない**。空力騒音は Curle + FFT を基本とし、FW-H は任意・互換性要検証
  （`aeroacoustics` スキル参照）。
- 低 Re の失速・ヒステリシスは RANS では出にくく、遷移モデルや LES が必要になりうる。
