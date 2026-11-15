"""
ヒステリシス掃引 プロッター
============================
使い方:
  uv run python scripts/plot_hysteresis.py

入力:
  docs/figures/sweep_results.csv  (run_sweep.py が生成)

生成物:
  docs/figures/hysteresis_cl_alpha.png  — Cl-α ヒステリシスループ
  docs/figures/hysteresis_cd_alpha.png  — Cd-α 比較
  docs/figures/hysteresis_cl_cd.png     — Cl-Cd 極曲線
"""

import csv
import math
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path

fm.fontManager.addfont(str(Path.home() / "Library/Fonts/NotoSansCJKjp-Regular.otf"))
plt.rcParams["font.family"] = "Noto Sans CJK JP"
plt.rcParams["axes.unicode_minus"] = False

RESULTS_CSV = Path("docs/figures/sweep_results.csv")
FIGDIR = Path("docs/figures")

# ── CSV 読み込み ──────────────────────────────────────────────────────────────
up, dn = [], []
with open(RESULTS_CSV) as f:
    for row in csv.DictReader(f):
        d = {"alpha": float(row["alpha"]), "Cl": float(row["Cl"]), "Cd": float(row["Cd"])}
        if row["direction"] == "up":
            up.append(d)
        else:
            dn.append(d)

up.sort(key=lambda x: x["alpha"])
dn.sort(key=lambda x: x["alpha"])

alpha_up = np.array([x["alpha"] for x in up])
Cl_up    = np.array([x["Cl"]    for x in up])
Cd_up    = np.array([x["Cd"]    for x in up])

alpha_dn = np.array([x["alpha"] for x in dn])
Cl_dn    = np.array([x["Cl"]    for x in dn])
Cd_dn    = np.array([x["Cd"]    for x in dn])

# ── Cl-α ヒステリシスループ ───────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

ax = axes[0]
ax.plot(alpha_up, Cl_up, "b-o", lw=2, ms=7, label="昇順 (0°→18°)")
ax.plot(alpha_dn, Cl_dn, "r--s", lw=2, ms=7, label="降順 (18°→0°)")

# ループ塗りつぶし（ヒステリシスがある場合）
if len(alpha_up) >= 2 and len(alpha_dn) >= 2:
    common_min = max(alpha_up.min(), alpha_dn.min())
    common_max = min(alpha_up.max(), alpha_dn.max())
    alpha_c = np.linspace(common_min, common_max, 100)
    try:
        Cl_up_i = np.interp(alpha_c, alpha_up, Cl_up)
        Cl_dn_i = np.interp(alpha_c, alpha_dn[::-1], Cl_dn[::-1])
        ax.fill_between(alpha_c, Cl_up_i, Cl_dn_i, alpha=0.12, color="purple",
                        label=f"ヒステリシス領域")
    except Exception:
        pass

# 薄翼理論参考線（線形域）
alpha_lin = np.linspace(0, 10, 50)
Cl_lin = 2 * math.pi * np.deg2rad(alpha_lin)
ax.plot(alpha_lin, Cl_lin, "k:", lw=1, label="薄翼理論 2πα")

ax.set_xlabel("迎角 α [°]", fontsize=12)
ax.set_ylabel("揚力係数 Cl", fontsize=12)
ax.set_title("NACA0012  Cl-α ヒステリシス掃引\nk-ω SST RANS, Re=2×10⁶", fontsize=12)
ax.legend(fontsize=10)
ax.grid(True, ls="--", alpha=0.4)
ax.set_xlim(-1, 20)

# 昇順/降順の Cl 差を計算して表示
common_alphas = set(alpha_up.tolist()) & set(alpha_dn.tolist())
if common_alphas:
    max_diff = 0.0
    diff_alpha = 0.0
    for a in sorted(common_alphas):
        c_up = Cl_up[np.where(alpha_up == a)[0][0]]
        c_dn = Cl_dn[np.where(alpha_dn == a)[0][0]]
        if abs(c_up - c_dn) > abs(max_diff):
            max_diff = c_up - c_dn
            diff_alpha = a
    ax.annotate(f"最大 ΔCl = {max_diff:.3f} @ α={diff_alpha:.0f}°",
                xy=(diff_alpha, (Cl_up[alpha_up == diff_alpha][0] +
                                 Cl_dn[alpha_dn == diff_alpha][0]) / 2),
                xytext=(diff_alpha + 1, -0.1),
                arrowprops=dict(arrowstyle="->", color="purple"),
                fontsize=9, color="purple")

# Cd-α
ax2 = axes[1]
ax2.plot(alpha_up, Cd_up, "b-o", lw=2, ms=7, label="昇順")
ax2.plot(alpha_dn, Cd_dn, "r--s", lw=2, ms=7, label="降順")
ax2.set_xlabel("迎角 α [°]", fontsize=12)
ax2.set_ylabel("抗力係数 Cd", fontsize=12)
ax2.set_title("Cd-α 掃引", fontsize=12)
ax2.legend(fontsize=10)
ax2.grid(True, ls="--", alpha=0.4)
ax2.set_xlim(-1, 20)

fig.suptitle(
    "NACA0012 ヒステリシス掃引  k-ω SST RANS  Re=2×10⁶  U∞=30 m/s",
    fontsize=13, y=1.01
)
fig.tight_layout()
out1 = FIGDIR / "hysteresis_cl_alpha.png"
fig.savefig(out1, dpi=150, bbox_inches="tight")
print(f"Saved: {out1}")
plt.close(fig)

# ── Cl/Cd 極曲線 ──────────────────────────────────────────────────────────────
fig2, ax3 = plt.subplots(figsize=(7, 7))
ax3.plot(Cd_up, Cl_up, "b-o", lw=2, ms=7, label="昇順")
ax3.plot(Cd_dn, Cl_dn, "r--s", lw=2, ms=7, label="降順")
for d in up:
    ax3.annotate(f"{d['alpha']:.0f}°", (d["Cd"], d["Cl"]),
                 textcoords="offset points", xytext=(5, 2), fontsize=7, color="blue")

ax3.set_xlabel("抗力係数 Cd", fontsize=12)
ax3.set_ylabel("揚力係数 Cl", fontsize=12)
ax3.set_title("NACA0012 極曲線\nk-ω SST RANS, Re=2×10⁶", fontsize=12)
ax3.legend(fontsize=10)
ax3.grid(True, ls="--", alpha=0.4)
fig2.tight_layout()
out2 = FIGDIR / "hysteresis_polar.png"
fig2.savefig(out2, dpi=150, bbox_inches="tight")
print(f"Saved: {out2}")
plt.close(fig2)

# ── テキストサマリー ──────────────────────────────────────────────────────────
print("\n─── 掃引サマリー ──────────────────────────────────────────")
print(f"  昇順: α = {alpha_up.min():.0f}°→{alpha_up.max():.0f}°  "
      f"Cl_max = {Cl_up.max():.3f} @ {alpha_up[Cl_up.argmax()]:.0f}°")
print(f"  降順: α = {alpha_dn.max():.0f}°→{alpha_dn.min():.0f}°  "
      f"Cl_max = {Cl_dn.max():.3f} @ {alpha_dn[Cl_dn.argmax()]:.0f}°")
if max_diff != 0.0:
    print(f"  最大 ΔCl:   {max_diff:.3f}  @ α = {diff_alpha:.0f}°")
    print(f"  {'ヒステリシスループ検出' if abs(max_diff) > 0.05 else 'ヒステリシス微小（RANS 定常の限界）'}")
print("──────────────────────────────────────────────────────────")
