# CLAUDE.md — airfoil-cfd プロジェクト指針

> このファイルは Claude Code がセッション開始時に読み込むプロジェクトの常設メモリです。
> OpenFOAM 13（Foundation 版 / openfoam.org, 2025-07-08 リリース）を前提とします。
> **旧来の `simpleFoam`/`pimpleFoam` 構文を絶対に使わないこと。** 理由は下記「最重要」を参照。

## プロジェクトの目的

Mac mini (Apple Silicon M4) 上で Multipass による Ubuntu VM をホストし、その中で
OpenFOAM 13 を使って翼型（airfoil）まわりの **非圧縮・低レイノルズ数** CFD を行う環境を構築・運用する。
達成したい解析：

1. 抗力 (Cd)・揚力 (Cl) の算出と、翼面圧力分布 (Cp) のプロット。
2. 失速近傍の **揚力ヒステリシス**（迎角 α の昇順掃引と降順掃引で Cl-α 曲線がループを描く現象）を再現できるか検証。
3. 翼型を差し替え可能にする（NACA 解析式 + 任意の `.dat` 座標）。
4. RANS だけでなく **LES** も実行可能にする。
5. 2D だけでなく **3D（スパン方向に押し出し）** 解析を行い、翼端渦 (wingtip vortex) を可視化する。
6. **空力騒音** を計算できるようにする。

## アーキテクチャ（役割分担）

- **ホスト (macOS)**: Claude Code が動く場所。uv で管理した Python 環境で
  - ジオメトリ生成（翼型座標 → 3D STL）
  - 後処理（Cp・Cl/Cd プロット、ヒステリシスループ、音響 FFT、VTK 可視化）
  を実行する。
- **ゲスト (Ubuntu VM, Multipass, instance 名 `openfoam`)**: OpenFOAM 13 本体（メッシュ生成・ソルバー）が動く。
- **共有ディレクトリ**: `multipass mount` でこのプロジェクトをホスト⇔VM で共有する。
  ホスト側で Python が書いた STL / ケースが、VM 側からそのまま見える状態にする。
- **連携手段**: Claude Code はホストから `multipass exec openfoam -- bash -lc "source <OFのbashrc> && <command>"`
  で OpenFOAM コマンドを VM 内実行する。詳細は `scripts/of.sh` ラッパー参照。

```
macOS host ── Claude Code + uv(Python: geometry/postprocess)
   │ multipass mount (共有: このリポジトリ)
   └── Ubuntu VM "openfoam" ── OpenFOAM 13 (blockMesh/snappyHexMesh/foamRun)
```

## 最重要：OpenFOAM 13 のモジュラーソルバー（旧構文厳禁）

OpenFOAM v11 以降、個別アプリケーションソルバー（simpleFoam, pisoFoam, pimpleFoam …）は
汎用ソルバー `foamRun` ＋ **ソルバーモジュール** に置き換えられた。本プロジェクトでは：

- 実行コマンドは **`foamRun`**（または `controlDict` に `solver incompressibleFluid;` を書いて `foamRun`）。
  - ❌ `simpleFoam` / `pimpleFoam` / `pisoFoam` は使わない（legacy 扱い）。
  - ✅ 非圧縮・等温乱流 → ソルバーモジュール **`incompressibleFluid`**（steady / transient 両対応、PIMPLE ベース）。
- `controlDict` の `application` エントリは v13 では省略可（既定で `foamRun`）。`solver incompressibleFluid;` を書く。
- **動粘性 `nu`** は `constant/transportProperties` ではなく **`constant/physicalProperties`** に書く。
- **乱流設定** は `constant/momentumTransport`（`simulationType RAS;` または `LES;`）。
- 定常 (RANS) と非定常 (LES) の切替は主に `system/fvSchemes` の `ddtSchemes`：
  - 定常: `ddtSchemes { default steadyState; }` ＋ `fvSolution` の SIMPLE/relaxation/residualControl。
  - 非定常: `ddtSchemes { default backward; }`（または `CrankNicolson 0.9`）＋ `adjustTimeStep`/`maxCo`。
- 並列実行: `decomposePar` → `multipass exec ... mpirun -np N foamRun -parallel` → `reconstructPar`。
- 困ったら VM 内で `foamInfo incompressibleFluid` / `foamInfo <BC名>` で正しい使い方と例を確認できる。
- チュートリアルの場所: VM 内 `$FOAM_TUTORIALS/modules/incompressibleFluid/`（参照元として有用）。

公式ユーザーガイド: https://doc.cfd.direct/openfoam/user-guide-v13/

## 空力騒音（重要な制約）

**FW-H（Ffowcs Williams–Hawkings）音響アナロジーは標準 OpenFOAM（Foundation 版）には含まれていない。**
そのため本プロジェクトでは段階的に：

1. **第一選択 = Curle アナロジー**：低マッハ数では翼面の双極子（dipole）音源が支配的なので、
   壁面圧力の時間履歴から Curle 積分で遠方場音圧を推定する。LES（または DDES）必須。
2. **壁面圧力プローブ + FFT**：観測点の圧力変動を高頻度サンプリングし、Python 側で FFT → SPL スペクトル・卓越周波数（渦放出など）を出す。
3. **（上級・任意）libAcoustics（Epikhin/Strijhak）で FW-H**：
   ただし主に ESI 版 OpenFOAM (.com) 向けで、Foundation v13 へのビルド互換性は要検証。
   互換性問題が出たら、(a) OpenFOAM-dev で試す、(b) ESI 版 OpenFOAM v2412+ の `noise`/FWH を別 VM で使う、を提案する。

→ 空力騒音タスクでは、いきなり FW-H を狙わず **必ず Curle + FFT から着手**すること。
詳細手順は `.claude/skills/aeroacoustics/SKILL.md`。

## 低レイノルズ数での注意（物理）

- 低 Re（およそ Re = 10^4〜10^5）では **層流剥離・再付着（laminar separation bubble）と遷移** が支配的。
  純粋な高Re型 RANS（k-ω SST 等）は失速・ヒステリシスを正しく出しにくい。
- ヒステリシス再現の現実的な順序：
  1. まず RANS（k-ω SST、可能なら遷移モデル `kOmegaSSTLM` / γ-Reθ）で α 掃引の傾向を見る。
  2. 本命は **LES（または wall-resolved / DDES）**。剥離・再付着の非定常性を解像する必要がある。
- ヒステリシスは「**前の α の収束解を次の α の初期条件にする**」連続掃引で初めて出る。
  各 α を独立に初期化すると履歴依存が消えてループが出ない。詳細は `hysteresis-sweep` スキル。

## スキル一覧（`.claude/skills/`）

| スキル | いつ使うか |
|---|---|
| `openfoam13-case-builder` | OF13 ケースの辞書（controlDict/fvSchemes/fvSolution/BC など）を作る・直すとき |
| `airfoil-geometry` | 翼型座標の生成・差し替え、2D/3D STL の作成 |
| `turbulence-rans-les` | RANS↔LES の切替、乱流モデル・壁面 y+ ・スキーム選定 |
| `aero-postprocess` | Cl/Cd 収束、Cp 分布、3D の渦可視化（Q 値/λ2/渦度） |
| `hysteresis-sweep` | 迎角の昇順／降順連続掃引でヒステリシスループを取得・判定 |
| `aeroacoustics` | Curle/FFT による空力騒音、(任意)FW-H |

## Python 環境（uv）

- `uv sync` で `.venv` を作成。`uv run <cmd>` または `uv run python -m airfoil_cfd.<module>` で実行。
- パッケージ本体は `src/airfoil_cfd/`。CLI エントリは `pyproject.toml` の `[project.scripts]` 参照。
- 依存追加は `uv add <pkg>`（`pip install` は使わない）。

## ワークフローの基本サイクル

1. `uv run afcfd geometry --airfoil naca2412 --span3d ...` でホスト側に STL 生成（→ 共有経由で VM へ）。
2. `scripts/of.sh "blockMesh && snappyHexMesh -overwrite && foamRun"` で VM 内メッシュ＆計算。
3. `uv run afcfd post ...` で Cl/Cd・Cp・可視化を生成。
4. 掃引は `uv run afcfd sweep ...`、音響は `uv run afcfd acoustics ...`。

## 規約

- ケースは `cases/template/` を `foamCloneCase`（または cp）で複製して `cases/runs/<名前>/` に作る。元テンプレは編集しない。
- 生成物（メッシュ・結果）は git 管理外（`.gitignore` 済）。図表は `docs/figures/` に保存。
- 単位系：非圧縮ソルバーの圧力 `p` は運動学的（m²/s²）。Cp・実圧力換算では基準密度 `rho` を明示する。
- 破壊的操作（VM 削除 `multipass delete`、大量ファイル削除）は実行前にユーザー確認を取る。
