"""Data-driven dominant-period detection for a 1-D numpy series.

Two independent estimators — autocorrelation with parabolic peak
interpolation, and an FFT periodogram — are combined into one
:meth:`detect_dominant_period` call. The function is pure: no I/O, no
network, no randomness.

NaN handling (cloud gaps stay NaN upstream): gaps up to
``max_gap_interp_days`` are linearly interpolated in time; longer runs of
NaNs are bridged by the same interpolation but the fraction of NaN input
scales the reported confidence down. More than ``max_nan_frac`` NaN input
caps confidence at 0.25 — the estimate is reported, not hidden, but flagged
as weak.

A confident result requires at least two full periods of data; shorter
spans get their confidence scaled by ``span / (2 * period)``.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np

__all__ = ["DominantPeriod", "detect_dominant_period"]


class DominantPeriod(NamedTuple):
    period_days: float   # estimated dominant period, in days (NaN if undetectable)
    confidence: float    # 0..1
    method: str          # "acf", "fft", "acf+fft", or "insufficient-data"


def _detrend_linear(x: np.ndarray) -> np.ndarray:
    t = np.arange(x.size, dtype=float)
    finite = np.isfinite(x)
    if finite.sum() < 2:
        return x - np.nanmean(x)
    a, b = np.polyfit(t[finite], x[finite], 1)
    return x - (a * t + b)


def _fill_nans(x: np.ndarray, dt_days: float, max_gap_interp_days: float) -> np.ndarray:
    """Linearly interpolate NaN gaps; record nothing, just fill."""
    out = x.astype(float).copy()
    finite = np.isfinite(out)
    if finite.all() or not finite.any():
        return out
    t = np.arange(out.size, dtype=float)
    # Gaps longer than the interpolation allowance are still interpolated
    # (ACF/FFT need a complete series); the NaN fraction scales confidence.
    out[~finite] = np.interp(t[~finite], t[finite], out[finite])
    return out


def _parabolic_offset(y0: float, y1: float, y2: float) -> float:
    """Sub-sample offset of a parabola through three points (peak at ~0)."""
    denom = y0 - 2.0 * y1 + y2
    if denom >= 0.0:  # not a peak (flat or valley) — no refinement
        return 0.0
    off = 0.5 * (y0 - y2) / denom
    return float(np.clip(off, -1.0, 1.0))


def _acf_period(x: np.ndarray, dt_days: float,
                min_period: float, max_period: float):
    n = x.size
    lo = max(2, int(round(min_period / dt_days)))
    hi = min(n - 2, int(round(max_period / dt_days)))
    if hi <= lo:
        return None
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    if denom <= 0.0 or not np.isfinite(denom):
        return None
    # FFT-based normalized autocorrelation.
    f = np.fft.rfft(xc, n=2 * n)
    acf = np.fft.irfft(f * np.conj(f))[:n].real / denom
    # Skip the trivial-continuity region: a smooth series has ACF ~ 1 at
    # small lags regardless of any true periodicity, so start the peak
    # search where the ACF first decays below 0.5.
    start = None
    for k in range(lo, hi):
        if acf[k] < 0.5:
            start = k
            break
    if start is None:
        return None  # never decayed inside the band — no ACF detection
    best, best_k = -np.inf, None
    for k in range(max(start, lo), hi + 1):
        if acf[k] > acf[k - 1] and acf[k] >= acf[k + 1] and acf[k] > best:
            best, best_k = acf[k], k
    if best_k is None or best < 0.35:
        return None
    off = _parabolic_offset(acf[best_k - 1], acf[best_k], acf[best_k + 1])
    period = (best_k + off) * dt_days
    # Confidence: normalized ACF peak height. 0.35 ~ weak, 0.9 ~ textbook.
    confidence = float(np.clip((best - 0.35) / 0.55, 0.0, 1.0))
    return period, confidence, best_k


def _fft_period(x: np.ndarray, dt_days: float,
                min_period: float, max_period: float):
    n = x.size
    xc = x - x.mean()
    # Hann taper to tame leakage; zero-pad 4x for frequency resolution.
    windowed = xc * np.hanning(n)
    m = 1
    while m < 4 * n:
        m *= 2
    spec = np.fft.rfft(windowed, n=m)
    power = (spec * np.conj(spec)).real
    freqs = np.fft.rfftfreq(m, d=dt_days)  # cycles per day
    periods = np.full_like(freqs, np.inf)
    nz = freqs > 0
    periods[nz] = 1.0 / freqs[nz]
    in_band = (periods >= min_period) & (periods <= max_period)
    if not in_band.any():
        return None
    band_power = float(power[in_band].sum())
    if not np.isfinite(band_power) or band_power <= 0.0:
        return None  # degenerate (e.g. constant) series — no spectrum
    idx = np.where(in_band)[0]
    k = idx[int(np.argmax(power[idx]))]
    if k <= 0 or k >= len(power) - 1:
        return None
    off = _parabolic_offset(power[k - 1], power[k], power[k + 1])
    # Refine in frequency space, then convert to period.
    f_refined = freqs[k] + off * (freqs[1] - freqs[0])
    if f_refined <= 0:
        return None
    period = 1.0 / f_refined
    # Confidence: share of in-band spectral power in the winning peak.
    share = float(power[k] / band_power)
    confidence = float(np.clip((share - 0.05) / 0.45, 0.0, 1.0))
    return period, confidence, k


def detect_dominant_period(
    series,
    dt_days: float = 1.0,
    min_period: Optional[float] = None,
    max_period: Optional[float] = None,
    max_nan_frac: float = 0.5,
    max_gap_interp_days: float = 7.0,
) -> DominantPeriod:
    """Estimate the dominant period of a 1-D series.

    Args:
        series: 1-D array-like of samples (NaNs allowed — cloud gaps).
        dt_days: nominal sample spacing in days.
        min_period: smallest period to consider, in days (default ``2*dt_days``).
        max_period: largest period to consider, in days (default half the span).
        max_nan_frac: above this NaN fraction, confidence is capped at 0.25.
        max_gap_interp_days: documented interpolation allowance (gaps of any
            length are still bridged; this parameter is kept for API
            stability and future per-gap policy).

    Returns:
        :class:`DominantPeriod` ``(period_days, confidence, method)`` where
        ``method`` is ``"acf"``, ``"fft"``, ``"acf+fft"`` (the two estimators
        agreed within 10%), or ``"insufficient-data"`` when the series has
        fewer than 3 finite samples or no in-band peak.
    """
    x = np.asarray(series, dtype=float).ravel()
    if dt_days <= 0:
        raise ValueError("dt_days must be positive")
    finite = np.isfinite(x)
    n_finite = int(finite.sum())
    if n_finite < 3:
        return DominantPeriod(float("nan"), 0.0, "insufficient-data")

    nan_frac = 1.0 - n_finite / x.size
    span_days = (x.size - 1) * dt_days
    if min_period is None:
        min_period = 2.0 * dt_days
    if max_period is None:
        max_period = span_days / 2.0
    if min_period <= 0 or max_period <= min_period:
        raise ValueError("need 0 < min_period < max_period")

    detrended = _detrend_linear(_fill_nans(x, dt_days, max_gap_interp_days))

    # Degenerate input: a constant or pure-trend series has no detectable
    # period. Compare the detrended RMS to the raw RMS — if detrending
    # removed essentially all variance, what remains is float residue whose
    # "spectrum" is shaped by the taper, not by any signal.
    raw = x[finite]
    raw_rms = float(np.sqrt(np.mean((raw - raw.mean()) ** 2)))
    det_rms = float(np.sqrt(np.mean(detrended ** 2)))
    if raw_rms == 0.0 or not np.isfinite(raw_rms) or det_rms < 1e-9 * raw_rms:
        return DominantPeriod(float("nan"), 0.0, "insufficient-data")

    acf = _acf_period(detrended, dt_days, min_period, max_period)
    fft = _fft_period(detrended, dt_days, min_period, max_period)

    if acf is None and fft is None:
        return DominantPeriod(float("nan"), 0.0, "insufficient-data")

    if acf is not None and fft is not None:
        p_acf, c_acf, _ = acf
        p_fft, c_fft, _ = fft
        mean_p = 0.5 * (p_acf + p_fft)
        if mean_p > 0 and abs(p_acf - p_fft) / mean_p < 0.10:
            period, confidence = mean_p, min(1.0, max(c_acf, c_fft) + 0.10)
            method = "acf+fft"
        elif c_acf >= c_fft:
            period, confidence, method = p_acf, c_acf, "acf"
        else:
            period, confidence, method = p_fft, c_fft, "fft"
    elif acf is not None:
        period, confidence, method = acf[0], acf[1], "acf"
    else:
        period, confidence, method = fft[0], fft[1], "fft"

    # Two-full-periods requirement: scale confidence by available span.
    if np.isfinite(period) and period > 0:
        need = 2.0 * period
        if span_days < need:
            confidence *= span_days / need

    # Heavy NaN load: report the estimate but cap the confidence.
    if nan_frac > max_nan_frac:
        confidence = min(confidence, 0.25)

    return DominantPeriod(float(period), float(np.clip(confidence, 0.0, 1.0)), method)
