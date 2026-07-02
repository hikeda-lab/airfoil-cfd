"""
NACA0012 LES 空力騒音解析 — コンパクト Curle + FFT
====================================================
使い方:
  uv run python scripts/plot_acoustics.py

手法:
  コンパクト音源近似（chord << 音響波長, f << c₀/chord=340 Hz で厳密）
  Curle 双極子公式:
    p'(r, θ, t) = [cos θ · D'(τ) + sin θ · L'(τ)] / (4π c₀ r)
    τ = t - r/c₀  (遅延時間),  θ: 流れ方向(x軸)からの仰角

  入力: docs/figures/les_forceCoeffs.dat (6283 サンプル, fs≈13 kHz)

生成物:
  docs/figures/acoustics_overview.png  — 力時間履歴 + SPL + 指向性
  docs/figures/acoustics_spl.png       — SPL スペクトル（詳細）
"""

import sys
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.gridspec as gridspec
from scipy import signal, interpolate
from pathlib import Path

fm.fontManager.addfont("/Users/hajime/Library/Fonts/NotoSansCJKjp-Regular.otf")
plt.rcParams["font.family"] = "Noto Sans CJK JP"

FIGDIR = Path("docs/figures")
FIGDIR.mkdir(parents=True, exist_ok=True)

# ── 物理定数 ──────────────────────────────────────────────────────────────
RHO   = 1.225        # 空気密度 [kg/m³]
C0    = 340.0        # 音速 [m/s]
U_INF = 30.0         # 主流速度 [m/s]
CHORD = 1.0          # 翼弦長 [m]
SPAN  = 0.5          # スパン [m]  (3D 計算の有限スパン)
ALPHA = 14.0         # 迎角 [deg]
P_REF = 20e-6        # 可聴閾値 [Pa]
R_OBS = 1.0          # 観測点距離 [m] (SPL は 1/r でスケール可能)
T_FLOW = CHORD / U_INF  # 流れ場通過時間 ≈ 0.0333 s

# 動圧 × 参照面積
Q_REF = 0.5 * RHO * U_INF**2 * CHORD * SPAN

# ── forceCoeffs 読み込み ─────────────────────────────────────────────────
def load_fc(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                rows.append([float(p) for p in parts[:4]])
            except ValueError:
                pass
    return np.array(rows)   # [t, Cm, Cd, Cl]

fc = load_fc(FIGDIR / "les_forceCoeffs.dat")
t_raw, Cm_raw, Cd_raw, Cl_raw = fc[:,0], fc[:,1], fc[:,2], fc[:,3]

# ── 定常発達後のみ使用（t ≥ 5 T_flow） ──────────────────────────────────
T_START = 5 * T_FLOW        # ≈ 0.167 s  (初期過渡を除外)
mask = t_raw >= T_START
t_d, Cl_d, Cd_d = t_raw[mask], Cl_raw[mask], Cd_raw[mask]
print(f"解析区間: t = {t_d[0]:.4f} → {t_d[-1]:.4f} s  ({len(t_d)} サンプル)")

# ── 均一時間グリッドへ補間（FFT に必要） ─────────────────────────────────
dt_med = float(np.median(np.diff(t_d)))
fs     = 1.0 / dt_med          # サンプリング周波数
t_uni  = np.arange(t_d[0], t_d[-1], dt_med)
Cl_u   = interpolate.interp1d(t_d, Cl_d, kind="linear")(t_uni)
Cd_u   = interpolate.interp1d(t_d, Cd_d, kind="linear")(t_uni)
N      = len(t_uni)
print(f"均一 dt = {dt_med*1e6:.1f} μs  fs = {fs:.0f} Hz  N = {N}")

# ── 実揚力 / 抗力 [N] ────────────────────────────────────────────────────
L_u = Cl_u * Q_REF   # 揚力 [N]
D_u = Cd_u * Q_REF   # 抗力 [N]

# ── dL/dt, dD/dt（中心差分） ─────────────────────────────────────────────
dLdt = np.gradient(L_u, dt_med)
dDdt = np.gradient(D_u, dt_med)

# ── コンパクト Curle 双極子音圧（θ = 90°, 真上の観測点） ────────────────
# p'(r, θ, t) = [cos θ·D'(τ) + sin θ·L'(τ)] / (4π c₀ r)
# θ=90° では cos θ=0, sin θ=1 → 揚力変動が支配的
THETA_DEG = 90.0
theta = np.deg2rad(THETA_DEG)
p_prime = (np.cos(theta) * dDdt + np.sin(theta) * dLdt) / (4 * np.pi * C0 * R_OBS)

p_rms  = float(np.sqrt(np.mean(p_prime**2)))
SPL_oa = 20 * np.log10(p_rms / P_REF)
print(f"\n[θ={THETA_DEG}°, r={R_OBS}m]  p'_rms = {p_rms*1000:.4f} mPa  OASPL = {SPL_oa:.1f} dB")

# ── Welch 法で PSD → SPL スペクトル ──────────────────────────────────────
nperseg  = min(2048, N // 4)   # セグメント長
noverlap = nperseg // 2
window   = "hann"

freq_L, psd_L = signal.welch(dLdt, fs=fs, window=window,
                              nperseg=nperseg, noverlap=noverlap)
freq_D, psd_D = signal.welch(dDdt, fs=fs, window=window,
                              nperseg=nperseg, noverlap=noverlap)

# 揚力変動 PSD → 遠方場音圧 PSD (sin θ = 1 at θ=90°)
psd_p   = (np.sin(theta)**2 * psd_L + np.cos(theta)**2 * psd_D) / (4 * np.pi * C0 * R_OBS)**2
df      = freq_L[1] - freq_L[0]
# SPL per Hz → 1/3 オクターブ相当幅で積分する代わりに狭帯域 SPL
spl_nb  = 10 * np.log10(psd_p / P_REF**2 * df + 1e-300)

# 有効周波数範囲（コンパクト近似: f << c₀/chord=340 Hz）
# ただし高周波も参考表示
f_mask = (freq_L >= 1.0) & (freq_L <= 3000.0)

# ── 卓越周波数の検出（5〜500 Hz 範囲） ───────────────────────────────────
f_range  = (freq_L >= 5) & (freq_L <= 500)
peak_idx = np.argmax(psd_L[f_range])
f_peak_L = freq_L[f_range][peak_idx]
St_peak  = f_peak_L * CHORD / U_INF
print(f"\n揚力変動卓越周波数: f = {f_peak_L:.1f} Hz  →  St = {St_peak:.3f}")
print(f"Strouhal 参考（St=0.2 for separated flow）: f = {0.2*U_INF/CHORD:.1f} Hz")

# ── 指向性パターン（複数角度でのOASPL） ──────────────────────────────────
thetas = np.linspace(0, 2*np.pi, 360)
spl_dir = np.zeros(360)
for i, th in enumerate(thetas):
    pp = (np.cos(th) * dDdt + np.sin(th) * dLdt) / (4 * np.pi * C0 * R_OBS)
    prms = float(np.sqrt(np.mean(pp**2)))
    spl_dir[i] = 20 * np.log10(max(prms, P_REF * 1e-6) / P_REF)

# ═══════════════════════════════════════════════════════════════════════════
# 図 1: 概要 4 パネル
# ═══════════════════════════════════════════════════════════════════════════
fig = plt.figure(figsize=(16, 12))
gs  = gridspec.GridSpec(2, 2, figure=fig, wspace=0.38, hspace=0.38)

# ─ (1) Cl/Cd 時間履歴 ─────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
ft_full = t_raw / T_FLOW
ax1.plot(ft_full, Cl_raw, lw=0.5, color="royalblue", label="Cl")
ax1.plot(ft_full, Cd_raw, lw=0.5, color="darkorange", label="Cd")
ax1.axvline(T_START / T_FLOW, ls="--", color="gray", lw=1.0, label=f"解析開始 t={T_START:.2f}s")
ax1.set_xlabel("t / T_flow (流れ場通過回数)")
ax1.set_ylabel("係数")
ax1.set_title("Cl/Cd 時間履歴")
ax1.legend(fontsize=8); ax1.grid(True, ls="--", alpha=0.4)

# ─ (2) 揚力・抗力 PSD ────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
ax2.semilogy(freq_L[f_mask], psd_L[f_mask], color="royalblue", lw=1.2, label="揚力 L")
ax2.semilogy(freq_D[f_mask], psd_D[f_mask], color="darkorange", lw=1.2, label="抗力 D")
ax2.axvline(f_peak_L, ls="--", color="royalblue", lw=1.5,
            label=f"卓越 {f_peak_L:.1f} Hz (St={St_peak:.3f})")
ax2.axvline(C0/CHORD, ls=":", color="gray", lw=1.0, label=f"コンパクト限界 {C0/CHORD:.0f} Hz")
ax2.set_xlabel("周波数 [Hz]")
ax2.set_ylabel("PSD [(N)²/Hz]")
ax2.set_title("空力変動 PSD (dL/dt, dD/dt に変換前)")
ax2.legend(fontsize=8); ax2.grid(True, which="both", ls="--", alpha=0.3)
ax2.set_xlim(1, 3000)

# ─ (3) 狭帯域 SPL スペクトル (θ=90°, r=1m) ──────────────────────────
ax3 = fig.add_subplot(gs[1, 0])
ax3.plot(freq_L[f_mask], spl_nb[f_mask], color="crimson", lw=1.0)
ax3.axvline(f_peak_L, ls="--", color="navy", lw=1.5,
            label=f"卓越 {f_peak_L:.1f} Hz")
ax3.axvline(C0/CHORD, ls=":", color="gray", lw=1.0, label="コンパクト限界")
ax3.axhline(SPL_oa, ls="-.", color="purple", lw=1.0,
            label=f"OASPL = {SPL_oa:.1f} dB")
ax3.set_xlabel("周波数 [Hz]")
ax3.set_ylabel("SPL [dB re 20μPa²/Hz]")
ax3.set_title(f"狭帯域 SPL スペクトル (θ={THETA_DEG}°, r={R_OBS} m)")
ax3.legend(fontsize=8); ax3.grid(True, which="both", ls="--", alpha=0.3)
ax3.set_xlim(1, 3000)

# ─ (4) 指向性パターン (極座標) ────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 1], projection="polar")
spl_plot = spl_dir - spl_dir.min() + 0    # 最小値を 0 dB 基準に正規化
ax4.plot(thetas, spl_plot, color="crimson", lw=1.5)
ax4.fill(thetas, spl_plot, alpha=0.15, color="crimson")
ax4.set_theta_offset(np.pi / 2)           # 90° を上方（揚力方向）に配置
ax4.set_theta_direction(-1)               # 時計回り
ax4.set_xlabel("OASPL 指向性\n(0°=流れ後方, 90°=上方)", labelpad=10)
ax4.set_title(f"指向性パターン\n(r={R_OBS}m, 最大={spl_dir.max():.1f} dB,  最小={spl_dir.min():.1f} dB)")

fig.suptitle(
    f"NACA0012 α={ALPHA}° LES WALE  Re=2e6  空力騒音解析（コンパクト Curle）\n"
    f"流れ: U∞={U_INF} m/s, chord={CHORD} m, span={SPAN} m  |  "
    f"卓越周波数 {f_peak_L:.1f} Hz (St={St_peak:.3f})  |  "
    f"OASPL = {SPL_oa:.1f} dB @ θ=90°, r={R_OBS} m",
    fontsize=10, y=1.01
)
fig.tight_layout()
out1 = FIGDIR / "acoustics_overview.png"
fig.savefig(out1, dpi=150, bbox_inches="tight")
print(f"\nSaved: {out1}")
plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# 図 2: SPL スペクトル 詳細（1 Hz〜2 kHz）
# ═══════════════════════════════════════════════════════════════════════════
# 1/3 オクターブバンド SPL（全点 FFT で df を最小化 → 低周波バンドを捕捉）
def third_octave_spl_pgram(t, signal_pa, f_min=2, f_max=2000):
    """全点ピリオドグラム（ゼロパディング×8）から 1/3 オクターブバンド SPL を計算"""
    n   = len(signal_pa)
    fs  = 1.0 / (t[1] - t[0])
    win = np.hanning(n)
    # ゼロパディングで df を下げる (df = fs/nfft; 8× → df ≈ 0.41 Hz で 13 Hz バンド捕捉)
    nfft  = n * 8
    enbw  = np.sum(win**2) / n
    freq  = np.fft.rfftfreq(nfft, 1/fs)
    sp    = np.fft.rfft(signal_pa * win, n=nfft)
    # 片側 PSD [Pa²/Hz] — ゼロパディングは振幅を変えないが bin 数が増えるため /nfft で正規化
    psd_one = (2 * np.abs(sp)**2) / (n * fs * enbw)
    psd_one[0] /= 2.0  # DC は除外

    bands = []
    f_c = f_min
    while f_c <= f_max:
        f_lo = f_c / 2**(1/6)
        f_hi = f_c * 2**(1/6)
        idx  = (freq >= f_lo) & (freq < f_hi)
        if idx.sum() >= 2:
            psd_int = np.trapezoid(psd_one[idx], freq[idx])
            if psd_int > P_REF**2 * 1e-6:
                bands.append((f_c, 10 * np.log10(psd_int / P_REF**2)))
        f_c *= 2**(1/3)
    return np.array(bands) if bands else np.zeros((0, 2))

bands = third_octave_spl_pgram(t_uni, p_prime)

fig2, axes = plt.subplots(2, 1, figsize=(12, 9))

# 狭帯域
axes[0].plot(freq_L[f_mask], spl_nb[f_mask], color="crimson", lw=0.8, label="狭帯域 SPL")
axes[0].axvline(f_peak_L, ls="--", color="navy", lw=1.5,
                label=f"卓越周波数 {f_peak_L:.1f} Hz (St={St_peak:.3f})")
axes[0].axvline(C0/CHORD, ls=":", color="gray", lw=1.2, label=f"コンパクト限界 {C0/CHORD:.0f} Hz")
axes[0].set_xscale("log")
axes[0].set_xlabel("周波数 [Hz]")
axes[0].set_ylabel("SPL [dB re 20μPa²/Hz]")
axes[0].set_title(f"狭帯域音圧スペクトル (θ=90°, r={R_OBS} m)")
axes[0].legend(fontsize=9); axes[0].grid(True, which="both", ls="--", alpha=0.3)
axes[0].set_xlim(1, 3000)
# Strouhal 軸（上）
ax_st = axes[0].twiny()
x_ticks = np.array([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 3000])
ax_st.set_xscale("log")
ax_st.set_xlim(axes[0].get_xlim())
st_vals = x_ticks * CHORD / U_INF
ax_st.set_xticks(x_ticks)
ax_st.set_xticklabels([f"{s:.3f}" for s in st_vals], fontsize=7)
ax_st.set_xlabel("Strouhal 数 St = f·c/U∞", fontsize=8)

# 1/3 オクターブ
if len(bands) > 0:
    axes[1].bar(bands[:,0], bands[:,1], width=bands[:,0]*0.23,
                color="steelblue", alpha=0.7, label="1/3 オクターブバンド SPL")
    axes[1].axvline(f_peak_L, ls="--", color="navy", lw=1.5,
                    label=f"卓越 {f_peak_L:.1f} Hz")
    axes[1].axhline(SPL_oa, ls="-.", color="purple", lw=1.0,
                    label=f"OASPL = {SPL_oa:.1f} dB")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("中心周波数 [Hz]")
    axes[1].set_ylabel("SPL [dB re 20μPa]")
    axes[1].set_title("1/3 オクターブバンド SPL")
    axes[1].legend(fontsize=9); axes[1].grid(True, which="both", ls="--", alpha=0.3)
    axes[1].set_xlim(1, 3000)

fig2.suptitle(
    f"NACA0012 α={ALPHA}°  LES  空力騒音 SPL スペクトル\n"
    f"コンパクト Curle 双極子  θ=90°(翼上方)  r={R_OBS} m  OASPL={SPL_oa:.1f} dB",
    fontsize=11
)
fig2.tight_layout()
out2 = FIGDIR / "acoustics_spl.png"
fig2.savefig(out2, dpi=150, bbox_inches="tight")
print(f"Saved: {out2}")
plt.close(fig2)

print("\n─── 解析サマリー ───────────────────────────────")
print(f"  コンパクト限界 (f < c₀/chord):  {C0/CHORD:.0f} Hz")
print(f"  卓越周波数:                      {f_peak_L:.1f} Hz")
print(f"  Strouhal 数:                     St = {St_peak:.3f}")
print(f"  OASPL (θ=90°, r={R_OBS}m):      {SPL_oa:.1f} dB")
print(f"  最大指向性 OASPL:                {spl_dir.max():.1f} dB @ "
      f"θ={np.degrees(thetas[np.argmax(spl_dir)]):.0f}°")
print(f"  指向性差（最大−最小）:           {spl_dir.max()-spl_dir.min():.1f} dB")
print("─────────────────────────────────────────────────")
