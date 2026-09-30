# survey-timescales

Timeframe-selection engine for the survey remote-sensing suite. Suggest the
right `[start, end]` window for a map reel *before* fetching a single byte:
annual cycles, climatological seasons, event-density bands, and multi-year
trend horizons — all from a curated registry shipped with the package,
optionally refined by data-driven dominant-period detection.

Part of the [survey/reel studio family](#interoperability): the engine that
answers *"what dates should this reel cover?"* — "temperature → 1 year",
"California fire → this year's May–Oct", "earthquakes → the trailing window
that holds 20–200 events", "night lights → the 12-year VIIRS era."

- **Package / import:** `survey-timescales` / `timescales`
- **Version:** 0.1.0 · **License:** MIT
- **Dependencies:** `numpy` + Python standard library. No network, no LLM,
  no UI framework — the registry is curated data shipped in the package,
  and the engine suggests windows; callers decide.

## Install

```bash
pip install git+https://github.com/crieck2010/survey-timescales.git
```

Python 3.9+.

## The idea in 30 seconds

```python
from timescales import suggest_window

# Temperature -> one full annual cycle, ending today
s = suggest_window("sst")
print(s.start, s.end, s.mode)
print(s.reason)
# 2025-09-30 2026-09-30 cycle
# 1-year window captures the full annual cycle (registry 365.25-day cycle — ...)

# Western-US fire -> this year's fire season, not 10 years of dead gaps
s = suggest_window("fire", region="california")
print(s.start, s.end, "|", s.reason)
# 2026-05-01 2026-09-30 | aligned to California fire season (May–Oct)

# Earthquakes -> trailing window sized to the event band
s = suggest_window("earthquakes", series=[date(2026, 9, 1), ...])
print(s.reason)
# trailing 16-day window holds 32 events (Earthquake events; target band 20–200)

# Your dates always win — the engine suggests, callers decide
s = suggest_window("fire", region="california",
                   start=date(2020, 1, 1), end=date(2020, 6, 1))
assert s.mode == "explicit"
```

## CLI

```bash
# Suggest a window
survey-timescales suggest --variable fire --region california --today 2026-09-30
# start:  2026-05-01
# end:    2026-09-30
# mode:   season
# reason: aligned to California fire season (May–Oct)

# With a data series (values | timestamps | date,value pairs)
survey-timescales suggest --variable earthquakes --series events.csv --json

# Inspect the registry
survey-timescales registry
survey-timescales registry --variable storm-tracks
```

`data.csv` shapes (all three accepted):
1. **one column of numbers** — value series, `--dt-days` spacing (default 1),
   trailing at `--today`;
2. **one column of dates/timestamps** — event timestamps;
3. **two columns `date,value`** — values with explicit dates.

A header row is tolerated. `tp` exists under two sources — disambiguate
with `--source era5` / `--source imerg`.

## Framing modes

| Mode | What it does | Example |
|---|---|---|
| `cycle` | N full periods of the dominant cycle (registry, or detected from `series`) | SST → 1-year window |
| `season` | Align to the registry's climatological season bounds; trim lulls | CA fire → May–Oct of the relevant year |
| `event-density` | Grow/shrink the trailing window until the event count lands in the registry band | Earthquakes → 20–200 events |
| `trend` | Multi-year/decadal window per the registry trend horizon | Night lights → 12-yr VIIRS era |
| `explicit` | Caller-supplied dates, returned verbatim — always wins | — |

Every suggestion carries a human-readable `reason` and provenance
(`registry_entry`, `detected_period_days`, `confidence`).

## Precedence contract

1. **Explicit dates win** — `suggest_window(..., start=, end=)` returns them
   verbatim (`mode="explicit"`); the engine never overrides.
2. **Registry** — the `(variable, region[, source])` entry supplies modes,
   season bounds, trend horizons, event-density bands.
3. **Data-driven detection** — with a `series`, cycle mode prefers the
   detected dominant period; season/event modes use it for trimming/banding.
4. **Safe defaults** — no series → registry values; event-density without a
   series → the registry's maximum window with an honest reason. Unknown
   variables raise `UnknownVariableError` (never a silent default); static
   underlays (GEBCO) raise `StaticVariableError`.

## Honest limits

- Registry seasons are **climatological approximations** — individual years
  shift (early/late onset, off-season storms/fires). The engine frames the
  *typical* season; callers with real data should verify.
- Detection needs **≥2 full periods** of data for a confident result;
  shorter spans get scaled-down confidence, and constant/pure-trend input
  reports `insufficient-data` rather than a bogus period.
- Event-density bands are **heuristics** tuned for readable reels, not
  statistical completeness claims.
- `tp` is two different products (ERA5 reanalysis vs IMERG satellite) —
  always disambiguate with `source=` when it matters.

## Docs

- `docs/METHODS.md` — the science: dominant periods, season alignment,
  event-density bands, lull trimming, detection math.
- `docs/REGISTRY.md` — the full seeded table and the basis for every
  season bound.
- `docs/API.md` — full function signatures and the precedence contract.
- `docs/INTEROP.md` — integration points: survey-viz, reel-studio, ops.

## Interoperability

Plays the "when" role in the suite: `survey-viz` parses *what/where*,
`survey-timescales` suggests *when*, `survey-currents` fetches,
`survey-viz` renders, `reel-studio` assembles. See `docs/INTEROP.md` for
exact call sites.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
