"""空力騒音: 壁面圧力からの Curle アナロジー、観測点圧力の FFT/SPL。

FW-H は標準 OpenFOAM(v13) に無いため、ここでは Curle(双極子近似) と FFT/SPL を提供する。
FW-H が必要な場合は aeroacoustics スキルの代替パス(libAcoustics/ESI版)を参照。
"""
from __future__ import annotations

import glob
import os

import numpy as np

P_REF = 20e-6   # 空気の基準音圧 [Pa]
C0 = 343.0      # 音速 [m/s]


# --------------------------------------------------------------------------- #
# 観測点圧力の読込（probes）
# --------------------------------------------------------------------------- #
def read_probes(case: str):
    """postProcessing/probes/<t>/p を読み (time, p[:, nprobe]) を返す。"""
    files = sorted(glob.glob(os.path.join(case, "postProcessing", "probes", "*", "p")))
    if not files:
        raise FileNotFoundError("probes の p 出力が見つかりません")
    rows = []
    with open(files[-1]) as f:
        for line in f:
            if line.startswith("#"):
                continue
            vals = [float(x) for x in line.replace("(", " ").replace(")", " ").split()]
            if vals:
                rows.append(vals)
    data = np.array(rows)
    return data[:, 0], data[:, 1:]


# --------------------------------------------------------------------------- #
# FFT / SPL
# --------------------------------------------------------------------------- #
def spl_spectrum(time: np.ndarray, p: np.ndarray, rho: float = 1.225):
    """圧力履歴(運動学的なら rho 倍して Pa に)を Welch PSD → SPL[dB] にする。

    戻り値: (freq, spl_db). p は 1 観測点の時系列。
    """
    from scipy.signal import welch

    dt = np.mean(np.diff(time))
    fs = 1.0 / dt
    p_pa = p * rho if np.max(np.abs(p)) < 1e3 else p   # 運動学的 p(m^2/s^2)→Pa 近似
    p_fluct = p_pa - p_pa.mean()
    f, psd = welch(p_fluct, fs=fs, nperseg=min(4096, len(p_fluct)))
    # PSD(Pa^2/Hz) → 各ビンの実効音圧 → SPL
    df = f[1] - f[0] if len(f) > 1 else 1.0
    p_rms_band = np.sqrt(psd * df)
    spl = 20 * np.log10(np.maximum(p_rms_band, 1e-30) / P_REF)
    return f, spl


def oaspl(time: np.ndarray, p: np.ndarray, rho: float = 1.225) -> float:
    """全帯域音圧レベル OASPL [dB]。"""
    p_pa = p * rho if np.max(np.abs(p)) < 1e3 else p
    p_rms = np.std(p_pa)
    return float(20 * np.log10(max(p_rms, 1e-30) / P_REF))


def strouhal(freq_peak: float, length: float, u_inf: float) -> float:
    """卓越周波数から Strouhal 数 St = f L / U。"""
    return freq_peak * length / u_inf


def plot_spl(case: str, u_inf: float, ref_len: float, out: str, probe: int = 0,
             rho: float = 1.225):
    import matplotlib.pyplot as plt

    t, p = read_probes(case)
    f, spl = spl_spectrum(t, p[:, probe], rho=rho)
    fpk = f[1 + int(np.argmax(spl[1:]))]
    st = strouhal(fpk, ref_len, u_inf)

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.semilogx(f[1:], spl[1:])
    ax.axvline(fpk, color="r", ls="--", lw=1,
               label=f"peak {fpk:.1f} Hz (St={st:.3f})")
    ax.set_xlabel("Frequency [Hz]"); ax.set_ylabel("SPL [dB]")
    ax.set_title(f"SPL spectrum  (OASPL={oaspl(t, p[:, probe], rho):.1f} dB)")
    ax.grid(True, which="both", alpha=0.3); ax.legend()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    return out


# --------------------------------------------------------------------------- #
# Curle アナロジー（遠方場双極子, 低マッハ近似）
# --------------------------------------------------------------------------- #
def curle_far_field(time, surf_p, centers, normals, areas, observer, rho=1.225):
    """剛体表面圧力履歴から観測点の遠方場音圧 p'(t) を Curle 積分で推定。

    引数:
      time      : (nt,) 時刻
      surf_p    : (nt, nface) 各面の圧力(Pa)
      centers   : (nface,3) 面中心
      normals   : (nface,3) 外向き単位法線
      areas     : (nface,) 面積
      observer  : (3,) 観測点
    近似: コンパクト音源・低マッハ。p'(x,t) ≈ (1/4πc0) ∂/∂t ∮ [p n·r̂ /|r| ] dS (遅延時間込み)
    """
    r_vec = observer[None, :] - centers
    r = np.linalg.norm(r_vec, axis=1)
    r_hat = r_vec / r[:, None]
    cos = np.einsum("fj,fj->f", normals, r_hat)        # n·r̂
    # 遅延時間を最近傍時刻に丸める簡易版（厳密にはリサンプル）
    dt = np.mean(np.diff(time))
    delay = (r / C0)
    shift = np.round(delay / dt).astype(int)

    nt = len(time)
    p_obs = np.zeros(nt)
    integrand = surf_p * (cos * areas / (4 * np.pi * C0 * r))[None, :]
    # 時間微分（双極子は ∂p/∂t）
    dpdt = np.gradient(integrand, dt, axis=0)
    for fidx in range(centers.shape[0]):
        s = shift[fidx]
        if s < nt:
            p_obs[s:] += dpdt[: nt - s, fidx]
    return time, p_obs
