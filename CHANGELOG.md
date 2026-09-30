# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-30

### Added
- `timescales.suggest_window(variable, region=None, series=None, intent=None, today=None, *, source=None, start=None, end=None, n_periods=1, dt_days=1.0, lull_threshold=None, min_period=None, max_period=None)`:
  the core framing engine. Returns a frozen `WindowSuggestion(start, end,
  mode, reason, registry_entry, detected_period_days, confidence)`.
  Five modes: `cycle` (N full periods of the dominant cycle), `season`
  (align to registry climatological bounds, lulls trimmed),
  `event-density` (grow/shrink the trailing window into the registry's
  event-count band, min/max caps respected), `trend` (multi-year/decadal
  horizon), `explicit` (caller dates returned verbatim).
- Precedence contract (enforced + documented in `docs/API.md`): explicit
  dates > registry > data-driven detection > safe defaults. Unknown
  variables raise `UnknownVariableError` (never a silent default); static
  underlays raise `StaticVariableError`.
- `timescales.detect_dominant_period(series, dt_days=1.0, min_period=None, max_period=None)`:
  data-driven dominant-period detection combining autocorrelation
  (parabolic peak interpolation, trivial-continuity region skipped) and
  an FFT periodogram (`acf+fft` when they agree within 10%). NaN-aware
  (cloud gaps interpolated for the estimate; confidence scaled by NaN
  fraction, capped at 0.25 above 50% NaN). Requires ≥2 full periods for a
  confident result (confidence scaled below that); constant/pure-trend
  input returns `insufficient-data` instead of a taper artifact. Pure
  function, deterministic.
- `timescales.load_registry(path=None)`: loads the curated
  `src/timescales/data/timescales.yaml` (28 entries covering all 13 suite
  data sources; GEBCO `bathymetry`/`elevation` marked static n/a).
  Lookup precedence `(variable, region, source)` → `(variable, region)` →
  `(variable, global)`; `tp` disambiguated by `source=` (era5/imerg);
  `chlorophyll` aliased to `ocean-color` (mirrors survey-viz). Ships a
  documented stdlib-only YAML-subset parser (deliberately not coercing
  `y/n/yes/no` to booleans, so the `na` mode stays a string).
- `timescales.trim_lulls(values, threshold, dt_days=1.0)`: leading/trailing
  sub-threshold (or NaN) trimming, returning index bounds.
- `survey-timescales` CLI: `suggest --variable/--region/--intent/--source/--series/--dt-days/--today/--json`
  and `registry [--variable] [--json]`. `--series` CSV accepts one column
  of values, one column of timestamps, or `date,value` pairs (header row
  tolerated).
- Docs: README, `docs/METHODS.md` (detection math, season alignment,
  event-density bands, lull trimming), `docs/REGISTRY.md` (full seeded
  table + basis for every season bound), `docs/API.md` (signatures +
  precedence contract), `docs/INTEROP.md` (exact integration points:
  survey-viz `parser.py` window resolution, reel-studio `app.py` Run step,
  `ops/daily_map_reel.py` REELS config).
- Tests: 61 tests, all passing (registry coverage incl. a PyYAML
  cross-check of the subset parser, synthetic-period detection incl. NaN
  handling and <2-period low confidence, every framing mode with a fixed
  today, lull trimming, precedence, CLI smoke tests).
