# PLAN.md — 開発ロードマップ

翼型 CFD 環境を段階的に構築する。各フェーズは「動く最小成果（マイルストーン）」を持ち、
前フェーズの成果物の上に積む。要件番号は `CLAUDE.md` の「プロジェクトの目的」に対応。

---

## Phase 0 — 環境構築（ホスト＋VM）

**目的**: Mac M4 上に Multipass + Ubuntu + OpenFOAM 13 + 共有マウント + uv Python を立ち上げる。

- [ ] `scripts/01_install_multipass.sh` — Homebrew で multipass を導入（または公式 pkg）。
- [ ] `scripts/02_launch_instance.sh` — instance `openfoam` を起動（コア/メモリ/ディスクを M4 に合わせて割当）。
- [ ] `scripts/03_install_openfoam13.sh` — `dl.openfoam.org` から OpenFOAM 13 を apt 導入、`bashrc` を source 設定。
- [ ] `multipass mount` でこのリポジトリをホスト⇔VM 共有（`scripts/04_mount_project.sh`）。
- [ ] `uv sync` でホスト側 Python 環境作成、`uv run afcfd --help` が通る。
- [ ] `scripts/of.sh "foamRun -help"` が VM 内で動く（連携の疎通確認）。
- [ ] （任意）ParaView を RDP/XQuartz 経由で起動できることを確認。

**完了条件**: VM 内チュートリアル `$FOAM_TUTORIALS/modules/incompressibleFluid/pitzDaily` を
`scripts/of.sh` 経由で計算→収束まで回せる。

---

## Phase 1 — 2D 翼型ベースライン（要件 1, 3）

**目的**: 翼型を差し替え可能にし、2D 非圧縮 RANS で Cl/Cd と Cp 分布を出す。

- [ ] `airfoil-geometry` スキル：NACA 4/5 桁の解析生成 + 任意 `.dat`（Selig）読込。
- [ ] 2D 用に薄いスパン（1 セル厚, `empty` 境界）で STL/メッシュ生成。
- [ ] `openfoam13-case-builder` スキル：`incompressibleFluid` 定常ケース一式を生成。
- [ ] `forceCoeffs` function object で Cl/Cd/Cm を出力、収束を確認。
- [ ] 壁面 `p` をサンプリングし、`aero-postprocess` で **Cp vs x/c** をプロット。
- [ ] 既知データ（例: NACA0012 の文献/XFOIL）と低迎角で突き合わせて妥当性確認。

**完了条件**: 翼型名を変えるだけで Cl/Cd と Cp 図が再生成できる。低 α で文献値と整合。

---

## Phase 2 — 迎角掃引とヒステリシス（要件 1）

**目的**: 失速近傍の Cl/Cd ヒステリシスをシミュレーションで再現できるか検証する。

- [ ] `hysteresis-sweep` スキル：迎角を流入速度ベクトルの回転で与える（再メッシュ不要）。
- [ ] **連続掃引**：α 昇順で前ケースの収束解を次の初期場に引き継ぎ、続けて降順掃引。
- [ ] 各 α の Cl/Cd を収集し、**Cl-α 昇順 vs 降順** を重ねてループ有無を判定。
- [ ] 定常 RANS で出ない場合は LES（Phase 4）+ 連続掃引へ移行（履歴依存の非定常を解像）。
- [ ] 低 Re では遷移モデル（`kOmegaSSTLM`）も試す。

**完了条件**: 昇順／降順で異なる Cl-α 経路（または剥離点の差）を定量的に提示し、
ヒステリシスの有無・幅を図示。再現できない場合は物理/モデル上の理由を考察として残す。

---

## Phase 3 — 3D 化と翼端渦（要件 5）

**目的**: スパン方向に押し出した 3D 翼で翼端渦を捉え可視化する。

- [ ] `airfoil-geometry`：スパン押し出しで 3D STL（(a) 無限翼=両側 `cyclic`/`slip`、(b) 有限翼=片側 symmetry・片側自由端）。
- [ ] 有限翼の翼端側に解像メッシュ（refinement region）を置き、渦を解像。
- [ ] `aero-postprocess`：Q 基準 / λ2 / 渦度の等値面を pyvista で可視化、翼端渦を確認。
- [ ] スパン分布（局所 Cl の翼幅方向変化、翼端での揚力減）を出力。

**完了条件**: 翼端渦の等値面図と、スパン方向揚力分布が得られる。

---

## Phase 4 — LES（要件 4）

**目的**: RANS に加え LES を実行可能にし、非定常剥離・渦構造・（音響の前提となる）圧力変動を解像する。

- [ ] `turbulence-rans-les` スキル：`momentumTransport` を `LES`（WALE/Smagorinsky/kEqn）に切替。
- [ ] `fvSchemes` を非定常・低散逸（`backward`/`CrankNicolson`, 中心系移流）に切替、`adjustTimeStep`+`maxCo`。
- [ ] LES 妥当性チェック：壁面解像 y+/Δx+/Δz+、平均化 `fieldAverage`、解像度指標。
- [ ] 平均 Cl/Cd（時間平均）と変動（rms）を出力。RANS 結果と比較。

**完了条件**: 同一翼型で RANS と LES を切替実行でき、LES で非定常渦構造と圧力変動が得られる。

---

## Phase 5 — 空力騒音（要件 6）

**目的**: LES の圧力場から空力騒音を評価する。

- [ ] `aeroacoustics` スキル：観測点 `probes`/壁面 `pressure` を高頻度サンプリング（LES 前提）。
- [ ] **Curle アナロジー**：壁面圧力 → 遠方場双極子音の推定（低マッハで主要）。
- [ ] **FFT/SPL**：Python (scipy) で時間履歴 → スペクトル、卓越周波数（渦放出/Strouhal）、OASPL。
- [ ] （任意）libAcoustics で FW-H を試行。互換性 NG なら代替案（dev / ESI 版）を提示。

**完了条件**: 観測点の SPL スペクトルと卓越周波数が出る。可能なら Curle/FW-H の遠方場指向性。

---

## 横断タスク（随時）

- 再現性: 各 run に使用した辞書・コミットハッシュ・物理条件を `cases/runs/<name>/META.yaml` に記録。
- 検証: 既知ベンチ（NACA0012、タンデム/単一円柱の渦放出など）で各機能を裏取り。
- 計算コスト管理: 2D→粗い3D→本番の順。LES は時間刻みとサンプリング頻度で容量が膨らむので注意。

## マイルストーン要約

| Phase | 成果 | 主要スキル |
|---|---|---|
| 0 | OF13 が VM で回る / uv 環境 | scripts |
| 1 | 2D Cl/Cd・Cp（翼型差替可） | geometry, case-builder, postprocess |
| 2 | ヒステリシスループ判定 | hysteresis-sweep |
| 3 | 3D 翼端渦の可視化 | geometry, postprocess |
| 4 | LES 実行・非定常解像 | turbulence-rans-les |
| 5 | 空力騒音 SPL | aeroacoustics |
