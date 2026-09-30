# Methods

The science behind `survey-timescales`: how the engine turns a variable name
into a date window, and where the math comes from.

## 1. The registry: curated timescales, not learned ones

Every entry in `src/timescales/data/timescales.yaml` records the
*characteristic timescales* of one observable as the suite's own adapters
see it:

- **cycle** — the dominant period in days (`365.25` for the annual cycle,
  leap-aware) and a one-line basis ("Annual insolation cycle").
- **season** — month/day bounds plus a named basis (e.g. "National Hurricane
  Center (NHC): the official Atlantic hurricane season is June 1–
  November 30"). See `docs/REGISTRY.md` for every bound's provenance.
- **trend** — a horizon in years tied to the instrument record
  (e.g. night-lights → 12 yr, the VIIRS Day/Night Band era 2012–present).
- **event-density** — a target event-count band plus hard min/max window
  caps (e.g. earthquakes → 20–200 events within 1–365 days).

The registry is shipped data, not a model: deterministic, versioned,
auditable, and overridable per call.

## 2. Dominant-period detection (`detect.py`)

Two independent estimators run on the linearly-detrended series; NaNs are
bridged by linear interpolation in time (cloud gaps stay NaN upstream —
the engine interpolates only for the spectral estimate, and the NaN
fraction scales the reported confidence; above 50% NaN, confidence is
capped at 0.25).

**Autocorrelation (ACF).** Normalized ACF via FFT. The naive "global max
peak" fails on smooth series (the trivial-continuity region near lag 0
always has ACF ≈ 1), so the search starts where the ACF first decays below
0.5, then takes the strongest local maximum in the `[min_period,
max_period]` band, refined by parabolic interpolation
(δ = ½·(r₋₁−r₊₁)/(r₋₁−2r₀+r₊₁)). Confidence maps the peak height from a
0.35 noise floor to a 0.9 textbook cycle.

**FFT periodogram.** Hann-tapered, 4× zero-padded real FFT; the winning
in-band peak is refined in frequency space by the same parabolic
interpolator, then converted to a period. Confidence is the peak's share
of in-band spectral power.

**Combination.** If the two estimates agree within 10%, the mean is
reported with `method="acf+fft"` and a +0.10 confidence bonus; otherwise
the higher-confidence estimate wins (`"acf"` / `"fft"`).

**The two-periods rule.** A confident result requires at least two full
periods of data: with a shorter span, confidence is scaled by
`span / (2·period)`. Constant and pure-trend series return
`("insufficient-data", 0.0)` rather than a taper-shaped artifact — the
detrended RMS is compared against the raw RMS, and anything below 10⁻⁹
relative is declared degenerate.

## 3. Season alignment (`framing.py`)

A registry season is a `(start_month, start_day) → (end_month, end_day)`
bound, possibly wrapping the year boundary (e.g. Oct→Mar for southeast
Australia). Given `today`, the engine picks the season instance containing
today (end clamped to today — we don't frame the future), else the most
recently completed instance. Leap-day overflow is clamped
(`calendar.monthrange`), so a Feb-29 bound never crashes in a common year.

Why climatological seasons at all: episodic phenomena (fire, tropical
cyclones, blooms) spend most of the year at zero. A fixed multi-year
window is mostly dead frames; aligning to the season concentrates the
reel on the activity that exists.

## 4. Event-density bands

For event variables (fire detections, storm tracks, earthquakes), the
window is *sized by count, not by calendar*: starting from the registry's
minimum window, the trailing window doubles until the event count reaches
the band's lower edge (capped at the maximum window), or halves from the
maximum while the count exceeds the band's upper edge (floored at the
minimum). When the data can't reach the band, the reason says so plainly
("sparse data; capped at the registry maximum") instead of silently
returning a misleading window. Bands are heuristics tuned for readable
reels — target counts that keep a vertical reel legible without overplot.

## 5. Lull trimming

For episodic data, leading/trailing sub-periods below an activity
threshold (default from the registry's `lull_threshold_per_day`) are
dropped: first/last index with `value ≥ threshold` (NaNs count as lull).
Applied in `season` mode over the aligned season, and in `event-density`
mode to counts series before band sizing. Thresholds are configurable per
call (`lull_threshold=`); the trims are reported in the `reason`.

## 6. What the engine does NOT do

- No forecasting: ComCat earthquakes, FIRMS fires, IBTrACS tracks are
  *observed* events; the engine sizes windows over history.
- No sub-daily phenomena: the finest registry cadence is daily.
- No per-year season adaptation: bounds are climatological; an unusually
  early/late season is the caller's data to correct.
- No significance testing on trends: `trend` mode frames a window, it does
  not test whether a trend exists (that's `survey-derive`'s job).
