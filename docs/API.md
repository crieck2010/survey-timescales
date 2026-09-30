# API reference

`timescales` — public surface. Engine/UI split: this package has zero UI
imports; it computes and returns plain data.

## `suggest_window(variable, region=None, series=None, intent=None, today=None, *, source=None, start=None, end=None, n_periods=1, dt_days=1.0, lull_threshold=None, min_period=None, max_period=None) -> WindowSuggestion`

Suggest a `[start, end]` window.

**Precedence contract** (enforced, in order):

1. **Explicit dates win.** `start=`/`end=` (both required if either is
   given) are returned verbatim with `mode="explicit"` — the suggestion
   path never overrides caller dates. A `start > end` raises `ValueError`.
2. **Registry.** The `(variable, region[, source])` entry is loaded;
   `UnknownVariableError` for unknown variables (message lists known
   variables), `StaticVariableError` for time-invariant underlays
   (`bathymetry`, `elevation`). `intent`, when given, must be one of the
   entry's `modes` or `ValueError` lists the valid intents.
3. **Data-driven detection.** When `series` is supplied: `cycle` mode uses
   the detected period if its confidence ≥ 0.30, else the registry period
   (reason says which); `season` mode trims lulls against the series;
   `event-density` mode sizes the window from the series.
4. **Safe defaults.** No series → registry-driven windows. `event-density`
   without a series → the registry's maximum window, with a reason that
   says a series is needed to hit the band. Nothing is ever silently
   invented.

`series` forms: `None`; a list/tuple of dates (`date`/`datetime`/ISO
strings) = event timestamps; a 1-D numeric numpy array (or numeric list) =
values at `dt_days` spacing, trailing (last sample = `today`); a list of
`(date, value)` pairs = values with explicit dates.

`today` defaults to `date.today()`; pass a fixed date for determinism.

## `WindowSuggestion` (frozen dataclass)

| field | type | meaning |
|---|---|---|
| `start`, `end` | `datetime.date` | suggested window (`start <= end` enforced) |
| `mode` | `str` | `cycle` / `season` / `event-density` / `trend` / `explicit` |
| `reason` | `str` | human-readable sentence, e.g. `"1-year window captures the full annual cycle"`, `"aligned to Atlantic hurricane season (Jun–Nov), lulls trimmed"` |
| `registry_entry` | `dict \| None` | the registry entry used (`None` for `explicit`) |
| `detected_period_days` | `float \| None` | data-driven period when used (cycle mode) |
| `confidence` | `float \| None` | detection confidence 0..1 when used |

`.to_dict()` serializes with ISO dates.

## `detect_dominant_period(series, dt_days=1.0, min_period=None, max_period=None, max_nan_frac=0.5, max_gap_interp_days=7.0) -> DominantPeriod`

Pure function. Returns the named tuple
`(period_days, confidence, method)` where `method` ∈
`{"acf", "fft", "acf+fft", "insufficient-data"}`. Defaults:
`min_period = 2·dt_days`, `max_period = span/2`. Confidence is scaled by
`span / (2·period)` below two full periods, and capped at 0.25 above
`max_nan_frac` NaN input. Raises `ValueError` for non-positive `dt_days`
or an inverted band.

## `load_registry(path=None) -> TimescaleRegistry`

Load the curated registry (cached; `_reload=True` re-reads).
`TimescaleRegistry.find(variable, region=None, source=None)` implements
the lookup precedence above. `TimescaleRegistry.variables()` lists known
variables.

## `trim_lulls(values, threshold, dt_days=1.0) -> (int, int)`

`(start_index, end_index_exclusive)` of the input with leading/trailing
sub-threshold (or NaN) sub-periods dropped; `(0, 0)` when nothing is
active.

## `canonical_variable(variable) -> str`

Lowercases and resolves legacy aliases (`chlorophyll` → `ocean-color`,
mirroring survey-viz).

## Errors

- `UnknownVariableError(ValueError)` — no registry entry; message lists
  known variables (or known sources for a bad `source=`).
- `StaticVariableError(ValueError)` — timeframe requested for a
  time-invariant underlay.

## CLI

`survey-timescales suggest --variable fire --region california [--intent season] [--source era5] [--series data.csv] [--dt-days 1.0] [--today YYYY-MM-DD] [--json]`

`survey-timescales registry [--variable X] [--json]`

CSV shapes: one column of numbers (values, `--dt-days` spacing, trailing
at `--today`); one column of dates/timestamps (events); two columns
`date,value` (pairs). A header row is tolerated. Note: a single column of
bare years (`2024`) parses as *values*, not timestamps — use full dates
for event timestamps.
