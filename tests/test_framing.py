"""Framing tests: every mode with a fixed today, precedence, lull trimming."""

import datetime as dt

import numpy as np
import pytest

from timescales.framing import WindowSuggestion, suggest_window, trim_lulls
from timescales.registry import StaticVariableError, UnknownVariableError

TODAY = dt.date(2026, 9, 30)


def _sine_series(period=365.0, days=3 * 365, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(days)
    return np.sin(2 * np.pi * t / period) + 0.2 * rng.standard_normal(days)


# ---------------------------------------------------------------- cycle --

def test_cycle_sst_one_year():
    s = suggest_window("sst", today=TODAY)
    assert s.mode == "cycle"
    assert s.start == dt.date(2025, 9, 30)
    assert s.end == TODAY
    assert "annual cycle" in s.reason
    assert s.registry_entry["variable"] == "sst"


def test_cycle_with_series_uses_detected_period():
    s = suggest_window("t2m", series=_sine_series(), today=TODAY)
    assert s.mode == "cycle"
    assert s.detected_period_days is not None
    assert abs(s.detected_period_days - 365.0) < 8.0
    assert 0.0 < s.confidence <= 1.0
    assert "detected" in s.reason


def test_cycle_n_periods():
    s = suggest_window("sst", n_periods=2, today=TODAY)
    assert (s.end - s.start).days == 2 * 365  # round(2 * 365.25)


def test_cycle_weak_detection_falls_back_to_registry():
    s = suggest_window("sst", series=np.ones(300), today=TODAY)  # no period
    assert s.mode == "cycle"
    assert s.detected_period_days is None  # no confident detection -> registry
    assert "registry" in s.reason


# --------------------------------------------------------------- season --

def test_season_california_fire():
    s = suggest_window("fire", region="california", today=TODAY)
    assert s.mode == "season"
    assert s.start == dt.date(2026, 5, 1)
    assert s.end == TODAY  # in-season today: clamped
    assert "California fire season" in s.reason


def test_season_before_start_uses_most_recent_completed():
    s = suggest_window("fire", region="california",
                       today=dt.date(2026, 2, 15))
    assert (s.start, s.end) == (dt.date(2025, 5, 1), dt.date(2025, 10, 31))


def test_season_atlantic_hurricane():
    s = suggest_window("storm-tracks", region="north-atlantic", today=TODAY)
    assert s.mode == "season"
    assert s.start == dt.date(2026, 6, 1)
    assert "Atlantic hurricane season" in s.reason


def test_wrap_season_spans_year_boundary():
    s = suggest_window("fire", region="australia-southeast", today=TODAY)
    assert (s.start, s.end) == (dt.date(2025, 10, 1), dt.date(2026, 3, 31))


def test_season_lull_trimming():
    # Episodic counts over the CA fire season: dead May, active Jun-Sep.
    days = (TODAY - dt.date(2026, 5, 1)).days + 1
    vals = np.zeros(days)
    vals[40:120] = 5.0  # active block mid-season
    s = suggest_window("fire", region="california", series=vals, today=TODAY,
                       lull_threshold=1.0)
    assert s.mode == "season"
    assert s.start > dt.date(2026, 5, 1)  # leading lull trimmed
    assert "lulls trimmed" in s.reason


# -------------------------------------------------------- event-density --

def _event_dates(n, span_days, seed=0):
    rng = np.random.default_rng(seed)
    offs = rng.uniform(0, span_days, n)
    return sorted(TODAY - dt.timedelta(days=float(o)) for o in offs)


def test_event_density_sizes_to_band():
    events = _event_dates(120, 60)
    s = suggest_window("earthquakes", series=events, today=TODAY)
    assert s.mode == "event-density"
    assert s.end == TODAY
    n = sum(1 for d in events if s.start <= d <= s.end)
    assert 20 <= n <= 200  # registry band


def test_event_density_sparse_data_caps_at_max():
    events = _event_dates(5, 365)
    s = suggest_window("earthquakes", series=events, today=TODAY)
    assert (s.end - s.start).days == 365  # registry max
    assert "below" in s.reason


def test_event_density_dense_data_floors_at_min():
    events = _event_dates(500, 2)  # 500 events in the last 2 days
    s = suggest_window("earthquakes", series=events, today=TODAY)
    assert (s.end - s.start).days == 1  # registry min
    assert "above" in s.reason


def test_event_density_no_series_uses_max_window_honestly():
    s = suggest_window("earthquakes", today=TODAY)
    assert (s.end - s.start).days == 365
    assert "no event series supplied" in s.reason


def test_event_density_counts_series():
    # 200 days of ~2 detections/day -> band 50-500 over ~7-180d
    rng = np.random.default_rng(4)
    counts = rng.poisson(2.0, 200).astype(float)
    s = suggest_window("fire", series=counts, today=TODAY)
    assert s.mode == "event-density"
    assert 7 <= (s.end - s.start).days <= 180


# ---------------------------------------------------------------- trend --

def test_trend_night_lights():
    s = suggest_window("night-lights", today=TODAY)
    assert s.mode == "trend"
    assert s.start == dt.date(2014, 9, 30)  # 12-yr VIIRS era
    assert s.end == TODAY
    assert "12-year" in s.reason


def test_trend_sea_ice_full_record():
    s = suggest_window("sea-ice", intent="trend", today=TODAY)
    assert (s.end - s.start).days == int(round(40 * 365.25))


# ----------------------------------------------------------- precedence --

def test_explicit_dates_always_win():
    s = suggest_window("fire", region="california",
                       series=_event_dates(300, 60),
                       intent="season", today=TODAY,
                       start=dt.date(2020, 1, 1), end=dt.date(2020, 6, 1))
    assert s.mode == "explicit"
    assert (s.start, s.end) == (dt.date(2020, 1, 1), dt.date(2020, 6, 1))
    assert "kept verbatim" in s.reason


def test_explicit_dates_need_both():
    with pytest.raises(ValueError):
        suggest_window("sst", today=TODAY, start=dt.date(2020, 1, 1))
    with pytest.raises(ValueError):
        suggest_window("sst", today=TODAY,
                       start=dt.date(2020, 6, 1), end=dt.date(2020, 1, 1))


def test_intent_override():
    s = suggest_window("fire", intent="trend", today=TODAY)  # default is event-density
    assert s.mode == "trend"


def test_invalid_intent_rejected():
    with pytest.raises(ValueError, match="valid intents"):
        suggest_window("sst", intent="event-density", today=TODAY)


def test_unknown_variable_raises_not_silent():
    with pytest.raises(UnknownVariableError):
        suggest_window("bogus", today=TODAY)


def test_static_variable_raises():
    with pytest.raises(StaticVariableError):
        suggest_window("bathymetry", today=TODAY)


# ------------------------------------------------------------ trim_lulls --

def test_trim_lulls_basic():
    vals = np.array([0, 0, 3, 5, 4, 0, 0], dtype=float)
    assert trim_lulls(vals, 1.0) == (2, 5)


def test_trim_lulls_all_lull():
    assert trim_lulls(np.zeros(10), 1.0) == (0, 0)


def test_trim_lulls_no_trim_needed():
    vals = np.array([2.0, 3.0, 4.0])
    assert trim_lulls(vals, 1.0) == (0, 3)


def test_trim_lulls_nans_are_lull():
    vals = np.array([np.nan, 0, 5, np.nan])
    assert trim_lulls(vals, 1.0) == (2, 3)


# ------------------------------------------------------- suggestion type --

def test_suggestion_is_frozen_and_validated():
    s = suggest_window("sst", today=TODAY)
    with pytest.raises(Exception):
        s.mode = "trend"  # frozen
    with pytest.raises(ValueError):
        WindowSuggestion(start=TODAY, end=TODAY - dt.timedelta(days=1),
                         mode="cycle", reason="x")
    d = s.to_dict()
    assert d["start"] == "2025-09-30" and d["mode"] == "cycle"
