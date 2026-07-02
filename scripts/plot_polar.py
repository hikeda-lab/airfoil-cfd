"""
NACA0012 Cl-α 極曲線のプロット
使い方: python3 scripts/plot_polar.py
"""
import subprocess, sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.font_manager as fm
from pathlib import Path

fm.fontManager.addfont("/Users/hajime/Library/Fonts/NotoSansCJKjp-Regular.otf")
plt.rcParams["font.family"] = "Noto Sans CJK JP"

VM      = "ubuntu@192.168.2.9"
KEY     = "/tmp/mp_key"
CSV_VM  = "/home/ubuntu/naca0012_sweep/polar.csv"
CSV_LOCAL = Path("docs/figures/polar.csv")
FIGDIR  = Path("docs/figures")
FIGDIR.mkdir(parents=True, exist_ok=True)

# ── VM から CSV を取得 ─────────────────────────────────────────────
r = subprocess.run(
    ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", VM, f"cat {CSV_VM}"],
    capture_output=True, text=True
)
if r.returncode != 0:
    sys.exit(f"Failed to read polar.csv: {r.stderr}")

print(r.stdout)
CSV_LOCAL.write_text(r.stdout)

# ── データ読み込み ─────────────────────────────────────────────────
lines = [l for l in r.stdout.strip().splitlines() if not l.startswith("alpha")]
alphas, Cls, Cds, Cms = [], [], [], []
for line in lines:
    vals = line.split(",")
    if "NaN" in vals:
        continue
    alphas.append(float(vals[0]))
    Cls.append(float(vals[1]))
    Cds.append(float(vals[2]))
    Cms.append(float(vals[3]))

alphas = np.array(alphas)
Cls    = np.array(Cls)
Cds    = np.array(Cds)
Cms    = np.array(Cms)

# NACA0012 実験値（Ladson 1988, Re=3e6）参考
exp_alpha = np.array([0, 2, 4, 6, 8, 10, 12, 14, 16])
exp_Cl    = np.array([0, 0.245, 0.467, 0.685, 0.871, 1.017, 1.126, 1.171, 1.073])
exp_Cd    = np.array([0.0062, 0.0062, 0.0066, 0.0072, 0.0083, 0.0099, 0.0135, 0.0199, 0.0331])

# ── プロット ───────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 5))
gs  = gridspec.GridSpec(1, 3, figure=fig, wspace=0.38)

# 1. Cl vs α
ax1 = fig.add_subplot(gs[0])
ax1.plot(alphas, Cls, "o-", color="royalblue", lw=2, label="RANS k-ω SST (Re=2e6)")
ax1.plot(exp_alpha, exp_Cl, "s--", color="tomato", lw=1.5, label="Exp. Ladson (Re=3e6)")
ax1.set_xlabel("α [deg]")
ax1.set_ylabel("Cl")
ax1.set_title("Lift Curve")
ax1.legend(fontsize=8)
ax1.grid(True, ls="--", alpha=0.5)

# 2. Drag polar (Cl vs Cd)
ax2 = fig.add_subplot(gs[1])
ax2.plot(Cds, Cls, "o-", color="royalblue", lw=2, label="RANS")
ax2.plot(exp_Cd, exp_Cl, "s--", color="tomato", lw=1.5, label="Exp.")
for i, a in enumerate(alphas):
    ax2.annotate(f"{a:.0f}°", (Cds[i], Cls[i]),
                 textcoords="offset points", xytext=(4, 0), fontsize=7)
ax2.set_xlabel("Cd")
ax2.set_ylabel("Cl")
ax2.set_title("Drag Polar")
ax2.legend(fontsize=8)
ax2.grid(True, ls="--", alpha=0.5)

# 3. L/D vs α
ax3 = fig.add_subplot(gs[2])
LD = Cls / np.where(Cds > 0, Cds, np.nan)
ax3.plot(alphas, LD, "o-", color="royalblue", lw=2, label="RANS")
ax3.set_xlabel("α [deg]")
ax3.set_ylabel("L/D  (= Cl/Cd)")
ax3.set_title("Lift-to-Drag Ratio")
ax3.legend(fontsize=8)
ax3.grid(True, ls="--", alpha=0.5)

fig.suptitle("NACA0012 Polar  —  incompressibleFluid / k-ω SST  —  Re = 2×10⁶",
             fontsize=11, y=1.01)
plt.tight_layout()
fig_path = FIGDIR / "naca0012_polar.png"
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
print(f"\nSaved: {fig_path}")
plt.show()
