"""Timeframe framing: turn a (variable, region, intent) into a date window.

The single entry point is :func:`suggest_window`. The engine *suggests*;
callers decide — explicit user-supplied dates are never overridden (see the
precedence contract in the docstring and in ``docs/API.md``).

Framing modes
-------------
- ``"cycle"``: N full periods of the dominant cycle (registry period, or
  detected from a supplied series).
- ``"season"``: align ``[start, end]`` to the registry's climatological
  season bounds for (variable, region), trimming lulls.
- ``"event-density"``: grow/shrink the trailing window until the event count
  lands inside the registry's configured band (min/max caps respected).
- ``"trend"``: multi-year/decadal window per the registry trend horizon.
- ``"explicit"``: caller-supplied dates returned verbatim (precedence #1).

``series`` forms (all optional):
- ``None`` — no data; framing is purely registry-driven.
- a list/tuple of dates (``datetime.date``/``datetime``/ISO strings) —
  event timestamps, for ``event-density`` mode.
- a 1-D numeric numpy array — values sampled every ``dt_days``, trailing
  (last sample = ``today``); used for cycle detection and lull trimming.
- a list of ``(date, value)`` pairs — values with explicit dates.
"""

from __future__ import annotations

import calendar
import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .detect import detect_dominant_period
from .registry import (RegistryEntry, StaticVariableError, UnknownVariableError,
                       canonical_variable, load_registry)

__all__ = [
    "WindowSuggestion",
    "suggest_window",
    "trim_lulls",
    "MODES",
]

MODES = ("cycle", "season", "event-density", "trend", "explicit")

#: Detection confidence below which cycle mode falls back to the registry period.
_DETECT_CONFIDENCE_FLOOR = 0.30


@dataclass(frozen=True)
class WindowSuggestion:
    """A suggested ``[start, end]`` window plus why it was chosen."""

    start: _dt.date
    end: _dt.date
    mode: str
    reason: str
    registry_entry: Optional[Dict[str, Any]] = None
    detected_period_days: Optional[float] = None
    confidence: Optional[float] = None

    def __post_init__(self):
        if self.start > self.end:
            raise ValueError(f"WindowSuggestion: start {self.start} after end {self.end}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "mode": self.mode,
            "reason": self.reason,
            "registry_entry": self.registry_entry,
            "detected_period_days": self.detected_period_days,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Series parsing
# ---------------------------------------------------------------------------

def _coerce_date(value: Any) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        return _dt.date.fromisoformat(value.strip())
    raise ValueError(f"cannot interpret {value!r} as a date")


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool)


def _parse_series(series, dt_days: float, today: _dt.date):
    """Return ("events", [date,...]) or ("values", [(date, float),...])."""
    if series is None:
        return None, []
    if isinstance(series, np.ndarray):
        arr = series
    else:
        arr = list(series)
    if isinstance(arr, np.ndarray) and arr.ndim == 1 and arr.dtype.kind in "iuf":
        n = arr.size
        dates = [today - _dt.timedelta(days=(n - 1 - i) * dt_days)
                 for i in range(n)]
        return "values", list(zip(dates, [float(v) for v in arr]))
    items = list(arr)
    if not items:
        return None, []
    if all(_is_number(v) for v in items):
        n = len(items)
        dates = [today - _dt.timedelta(days=(n - 1 - i) * dt_days)
                 for i in range(n)]
        return "values", list(zip(dates, [float(v) for v in items]))
    # (date, value) pairs?
    if all(isinstance(v, (list, tuple)) and len(v) == 2 for v in items):
        pairs = [(_coerce_date(d), float(v)) for d, v in items]
        pairs.sort(key=lambda p: p[0])
        return "values", pairs
    # Otherwise: event timestamps.
    dates = sorted(_coerce_date(v) for v in items)
    return "events", dates


# ---------------------------------------------------------------------------
# Lull trimming
# ---------------------------------------------------------------------------

def trim_lulls(values, threshold: float, dt_days: float = 1.0) -> Tuple[int, int]:
    """Drop leading/trailing sub-periods below an activity threshold.

    Args:
        values: 1-D array-like of activity values (counts, detections, ...).
        threshold: values strictly below this are "lull".
        dt_days: sample spacing (accepted for API symmetry; trimming is
            index-based).

    Returns:
        ``(start_index, end_index_exclusive)`` of the trimmed slice. All-NaN
        or all-lull input trims to an empty slice ``(n, n)``... actually to
        ``(first_active, n)`` semantics: returns ``(0, 0)`` when nothing is
        active.
    """
    v = np.asarray(values, dtype=float).ravel()
    active = np.isfinite(v) & (v >= threshold)
    if not active.any():
        return 0, 0
    idx = np.where(active)[0]
    return int(idx[0]), int(idx[-1]) + 1


# ---------------------------------------------------------------------------
# Season alignment
# ---------------------------------------------------------------------------

def _month_day(year: int, month: int, day: int) -> _dt.date:
    last = calendar.monthrange(year, month)[1]
    return _dt.date(year, month, min(day, last))


def _season_bounds(season: Dict[str, Any], year: int) -> Tuple[_dt.date, _dt.date]:
    sm, sd = int(season["start_month"]), int(season["start_day"])
    em, ed = int(season["end_month"]), int(season["end_day"])
    start = _month_day(year, sm, sd)
    if (em, ed) < (sm, sd):  # wrap season spans the year boundary
        end = _month_day(year + 1, em, ed)
    else:
        end = _month_day(year, em, ed)
    return start, end


def _season_instance(season: Dict[str, Any], today: _dt.date) -> Tuple[_dt.date, _dt.date]:
    """Pick the season instance framing ``today``: the one containing today
    (clamped to today), else the most recently completed one."""
    for year in (today.year - 1, today.year, today.year + 1):
        s, e = _season_bounds(season, year)
        if s <= today <= e:
            return s, min(e, today)
    best = None
    for year in (today.year - 2, today.year - 1, today.year):
        s, e = _season_bounds(season, year)
        if e <= today and (best is None or e > best[1]):
            best = (s, e)
    if best is not None:
        return best
    s, e = _season_bounds(season, today.year + 1)  # all future; earliest upcoming
    return s, e


def _season_label(season: Dict[str, Any]) -> str:
    sm = calendar.month_abbr[int(season["start_month"])]
    em = calendar.month_abbr[int(season["end_month"])]
    return f"{sm}\u2013{em}"


# ---------------------------------------------------------------------------
# suggest_window
# ---------------------------------------------------------------------------

def _fmt_days(n: float) -> str:
    n = int(round(n))
    return f"{n:,d}"


def suggest_window(
    variable: str,
    region: Optional[str] = None,
    series=None,
    intent: Optional[str] = None,
    today: Optional[_dt.date] = None,
    *,
    source: Optional[str] = None,
    start: Optional[_dt.date] = None,
    end: Optional[_dt.date] = None,
    n_periods: int = 1,
    dt_days: float = 1.0,
    lull_threshold: Optional[float] = None,
    min_period: Optional[float] = None,
    max_period: Optional[float] = None,
) -> WindowSuggestion:
    """Suggest a ``[start, end]`` window for ``(variable, region)``.

    Precedence contract (the engine suggests; callers decide):

    1. **Explicit dates win.** If ``start``/``end`` are supplied they are
       returned verbatim with ``mode="explicit"`` — never overridden.
    2. **Registry.** The (variable, region[, source]) entry supplies modes,
       season bounds, trend horizons, and event-density bands.
    3. **Data-driven detection.** When ``series`` is supplied, cycle mode
       prefers the detected dominant period and season/event-density modes
       use the series for trimming and band sizing.
    4. **Safe defaults.** Without a series, registry values drive the
       window; event-density without a series falls back to the registry's
       maximum window with an honest reason. Unknown variables raise
       :class:`UnknownVariableError` (never a silent default); static
       underlays raise :class:`StaticVariableError`.

    Args:
        variable: canonical suite variable key (e.g. ``"sst"``, ``"fire"``).
        region: gazetteer region key (e.g. ``"california"``); ``None`` uses
            the variable's global default.
        series: optional data — event timestamps, a 1-D value array
            (``dt_days`` spacing, trailing at ``today``), or
            ``(date, value)`` pairs.
        intent: force a framing mode; must be listed in the entry's modes.
        today: reference date (defaults to today; exposed for determinism).
        source: disambiguate multi-source variables (e.g. ``tp`` → era5/imerg).
        start/end: explicit caller dates — always win when both supplied.
        n_periods: full cycles spanned in ``"cycle"`` mode.
        dt_days: sample spacing of a value-array ``series``.
        lull_threshold: activity threshold for lull trimming (default from
            the registry's event-density band, else 0).
        min_period/max_period: detection search band in days (cycle mode).

    Returns:
        :class:`WindowSuggestion` with provenance fields populated.
    """
    today = today or _dt.date.today()
    if isinstance(today, _dt.datetime):
        today = today.date()
    variable = canonical_variable(variable)

    # --- Precedence 1: explicit dates always win ---------------------------
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("suggest_window: pass both start and end, or neither")
        start_d, end_d = _coerce_date(start), _coerce_date(end)
        if start_d > end_d:
            raise ValueError(f"suggest_window: start {start_d} after end {end_d}")
        return WindowSuggestion(
            start=start_d, end=end_d, mode="explicit",
            reason=(f"explicit user dates kept verbatim "
                    f"({start_d.isoformat()} to {end_d.isoformat()}); "
                    f"the engine suggests, callers decide."),
            registry_entry=None, detected_period_days=None, confidence=None,
        )

    # --- Precedence 2: registry --------------------------------------------
    entry = load_registry().find(variable, region=region, source=source)
    if intent is not None and intent not in entry.modes:
        raise ValueError(
            f"intent {intent!r} not available for {variable!r}: "
            f"valid intents are {list(entry.modes)}"
        )
    mode = intent or entry.default_mode
    provenance = entry.to_dict()
    kind, payload = _parse_series(series, dt_days, today)

    # --- Mode: cycle --------------------------------------------------------
    if mode == "cycle":
        period = entry.cycle_period_days
        if period is None:
            raise ValueError(
                f"variable {variable!r} has no cycle in the registry; "
                f"valid intents are {list(entry.modes)}"
            )
        detected = None
        confidence = None
        if kind == "values" and payload:
            vals = np.array([v for _, v in payload])
            det = detect_dominant_period(vals, dt_days=dt_days,
                                         min_period=min_period,
                                         max_period=max_period)
            if np.isfinite(det.period_days) and det.confidence >= _DETECT_CONFIDENCE_FLOOR:
                period, detected, confidence = det.period_days, det.period_days, det.confidence
                basis = (f"detected {period:.1f}-day period, "
                         f"confidence {confidence:.2f} ({det.method})")
            else:
                basis = (f"no confident period in the series ({det.method}); "
                         f"registry {period:g}-day cycle")
        else:
            basis = f"registry {period:g}-day cycle"
            if entry.cycle_basis:
                basis += f" — {entry.cycle_basis}"
        if n_periods < 1:
            raise ValueError("n_periods must be >= 1")
        span = int(round(n_periods * period))
        end_d = today
        start_d = end_d - _dt.timedelta(days=span)
        if abs(period - 365.25) < 2.0 and n_periods == 1:
            reason = f"1-year window captures the full annual cycle ({basis})"
        else:
            reason = (f"{_fmt_days(span)}-day window spans {n_periods} full "
                      f"{period:.1f}-day cycle(s) ({basis})")
        return WindowSuggestion(start_d, end_d, "cycle", reason, provenance,
                                detected, confidence)

    # --- Mode: season -------------------------------------------------------
    if mode == "season":
        season = entry.season
        if not season:
            raise ValueError(
                f"variable {variable!r} has no registry season for "
                f"region {region!r}; valid intents are {list(entry.modes)}"
            )
        start_d, end_d = _season_instance(season, today)
        reason = (f"aligned to {season.get('name', 'season')} "
                  f"({_season_label(season)})")
        if kind == "values" and payload:
            thresh = (lull_threshold if lull_threshold is not None
                      else _default_lull_threshold(entry))
            inside = [(d, v) for d, v in payload if start_d <= d <= end_d]
            if len(inside) >= 3:
                vals = np.array([v for _, v in inside])
                lo, hi = trim_lulls(vals, thresh, dt_days)
                if hi > lo:
                    start_d = inside[lo][0]
                    end_d = min(inside[hi - 1][0], today)
                    reason += ", lulls trimmed"
        return WindowSuggestion(start_d, end_d, "season", reason, provenance,
                                None, None)

    # --- Mode: event-density ------------------------------------------------
    if mode == "event-density":
        band = entry.event_density
        if not band:
            raise ValueError(
                f"variable {variable!r} has no event-density band in the registry; "
                f"valid intents are {list(entry.modes)}"
            )
        lo_c, tgt_c, hi_c = (int(band["min_count"]), int(band["target_count"]),
                             int(band["max_count"]))
        min_w, max_w = int(band["min_window_days"]), int(band["max_window_days"])
        thresh = (lull_threshold if lull_threshold is not None
                  else float(band.get("lull_threshold_per_day", 0.0)))
        if kind == "events":
            event_dates = sorted(payload)

            def count_fn(cutoff):
                return sum(1 for d in event_dates if cutoff <= d <= today)
            trimmed_note = ""
        elif kind == "values":
            # Counts per bin: the event count is the sum of bin values.
            # Lull-trim the series first so dead leading/trailing bins don't
            # inflate the window.
            vals = np.array([v for _, v in payload])
            tlo, thi = trim_lulls(vals, thresh, dt_days)
            trimmed = payload[tlo:thi] if thi > tlo else []
            trimmed_note = ", lulls trimmed" if thi > tlo and (tlo, thi) != (0, len(payload)) else ""

            def count_fn(cutoff):
                return int(round(sum(max(0.0, v) for d, v in trimmed
                                     if cutoff <= d <= today and np.isfinite(v))))
        else:
            count_fn = None
        if count_fn is None:
            start_d = today - _dt.timedelta(days=max_w)
            reason = (f"no event series supplied; fell back to the registry "
                      f"maximum {_fmt_days(max_w)}-day window \u2014 supply a series "
                      f"to size the window to the target band "
                      f"({lo_c}\u2013{hi_c} events)")
            return WindowSuggestion(start_d, today, "event-density", reason,
                                    provenance, None, None)
        w = min_w
        n = count_fn(today - _dt.timedelta(days=w))
        while n < lo_c and w < max_w:
            w = min(max_w, w * 2)
            n = count_fn(today - _dt.timedelta(days=w))
        while n > hi_c and w > min_w:
            w = max(min_w, w // 2)
            n = count_fn(today - _dt.timedelta(days=w))
        start_d = today - _dt.timedelta(days=w)
        span_s = _fmt_days(w)
        label = entry.long_name or variable
        band_s = f"target band {lo_c}\u2013{hi_c}"
        if lo_c <= n <= hi_c:
            reason = (f"trailing {span_s}-day window holds {n} events "
                      f"({label}; {band_s}){trimmed_note}")
        elif n < lo_c:
            reason = (f"trailing {span_s}-day window holds {n} events "
                      f"({label}) \u2014 below the {band_s} "
                      f"(sparse data; capped at the registry maximum){trimmed_note}")
        else:
            reason = (f"trailing {span_s}-day window holds {n} events "
                      f"({label}) \u2014 above the {band_s} "
                      f"(dense data; floored at the registry minimum){trimmed_note}")
        return WindowSuggestion(start_d, today, "event-density", reason,
                                provenance, None, None)

    # --- Mode: trend --------------------------------------------------------
    if mode == "trend":
        years = entry.trend_years
        if years is None:
            raise ValueError(
                f"variable {variable!r} has no trend horizon in the registry; "
                f"valid intents are {list(entry.modes)}"
            )
        span = int(round(years * 365.25))
        end_d = today
        start_d = end_d - _dt.timedelta(days=span)
        label = entry.long_name or variable
        basis = f" ({entry.trend_basis})" if entry.trend_basis else ""
        reason = f"{years:g}-year window frames the long-term {label} trend{basis}"
        return WindowSuggestion(start_d, end_d, "trend", reason, provenance,
                                None, None)

    raise ValueError(f"unknown framing mode {mode!r}")


def _default_lull_threshold(entry: RegistryEntry) -> float:
    band = entry.event_density or {}
    return float(band.get("lull_threshold_per_day", 0.0))
