"""Detection tests: synthetic series with known periods, NaNs, edge cases."""

import numpy as np
import pytest

from timescales.detect import detect_dominant_period


def _sine(period_days, n_days, noise=0.2, seed=0, dt=1.0):
    rng = np.random.default_rng(seed)
    t = np.arange(n_days) * dt
    return np.sin(2 * np.pi * t / period_days) + noise * rng.standard_normal(n_days)


def test_annual_cycle_recovered():
    det = detect_dominant_period(_sine(365.0, 3 * 365))
    assert abs(det.period_days - 365.0) < 8.0
    assert det.confidence > 0.4
    assert det.method in ("acf", "fft", "acf+fft")


def test_monthly_cycle_recovered():
    det = detect_dominant_period(_sine(30.0, 400))
    assert abs(det.period_days - 30.0) < 1.5
    assert det.confidence > 0.7


def test_semiannual_harmonic_recovered():
    det = detect_dominant_period(_sine(182.6, 3 * 365, seed=3))
    assert abs(det.period_days - 182.6) < 6.0


def test_nan_gaps_tolerated():
    s = _sine(365.0, 3 * 365)
    s[100:130] = np.nan  # a month-long cloud gap
    s[800:805] = np.nan
    det = detect_dominant_period(s)
    assert abs(det.period_days - 365.0) < 8.0
    assert det.confidence > 0.3


def test_heavy_nan_load_caps_confidence():
    rng = np.random.default_rng(0)
    s = _sine(365.0, 3 * 365)
    s[rng.random(s.size) < 0.6] = np.nan
    det = detect_dominant_period(s)
    assert det.confidence <= 0.25  # reported, but flagged weak


def test_fewer_than_two_periods_gets_low_confidence():
    det = detect_dominant_period(_sine(365.0, 400))  # ~1.1 periods
    assert det.confidence < 0.75


def test_constant_series_is_insufficient():
    det = detect_dominant_period(np.ones(500))
    assert det.method == "insufficient-data"
    assert det.confidence == 0.0


def test_pure_trend_is_insufficient():
    det = detect_dominant_period(np.linspace(0, 1, 1000))
    assert det.method == "insufficient-data"


def test_tiny_series_is_insufficient():
    det = detect_dominant_period([np.nan, 1.0])
    assert det.method == "insufficient-data"
    assert np.isnan(det.period_days)


def test_pure_noise_gets_low_confidence():
    rng = np.random.default_rng(7)
    det = detect_dominant_period(rng.standard_normal(1000))
    assert det.confidence < 0.5


def test_deterministic():
    s = _sine(365.0, 3 * 365)
    a = detect_dominant_period(s)
    b = detect_dominant_period(s)
    assert a == b


def test_invalid_dt_rejected():
    with pytest.raises(ValueError):
        detect_dominant_period(np.ones(100), dt_days=0)


def test_monthly_cadence_series():
    det = detect_dominant_period(_sine(365.25, 120, dt=30.44, seed=5),
                                 dt_days=30.44)
    assert abs(det.period_days - 365.25) < 40.0
    assert det.confidence > 0.3
