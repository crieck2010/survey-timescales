# Interop

`survey-timescales` plays the **"when"** role in the suite pipeline:

```
describe → survey-viz parser (what/where) → survey-timescales (when)
         → survey-currents (fetch) → survey-viz (render)
         → survey-derive (products) → reel-studio (assemble)
```

The engine suggests; callers decide. Integration is one call —
`suggest_window(variable, region_key, ...)` — plus honoring the
precedence contract (explicit user dates always win; see `docs/API.md`).

## 1. survey-viz — `src/viz/parser.py` window resolution

**Call site:** `parse_description(text, title=None, today=None)` (line
1023), which resolves time phrases via `_parse_time(text, today)` (line
529) — "past 5 years", "last summer" (`_last_summer_window`, line 520),
explicit ranges (`_EXPLICIT_RANGE`).

**Integration point:** when `_parse_time` finds no time phrase
(`(None, None)`), the parser currently falls back to a fixed default
window. Replace that fallback with:

```python
from timescales import suggest_window
sug = suggest_window(variable, region=region_key, today=today)
start, end = sug.start, sug.end
```

Effect: "California wildfires" with no date phrase → this year's May–Oct
(season mode); "global earthquakes" → trailing window sized to the
20–200 event band; "sea surface temperature" → 1-year cycle window.
Explicit phrases ("2020–2022", "last summer") keep working untouched —
precedence #1 is the parser's own explicit dates.

Variable keys align 1:1 with `spec.py` `KNOWN_VARIABLES` (including the
`chlorophyll` → `ocean-color` alias); region keys align with the
gazetteer `regions.yaml`. `bathymetry`/`elevation` raise
`StaticVariableError` — the parser should surface that as "this underlay
has no time dimension" rather than a window.

## 2. reel-studio — `app.py` date pickers

**Call sites:** `_run_step` (line 1155) builds the `VizSpec` from
`spec_dict` and hands it to `pipeline.run_pipeline`; the Run step
currently inherits whatever dates the description parsed (or the
parser's default).

**Integration point:** add a "Suggest window" affordance next to the Run
step's date display (and in the step-1 description flow): a button that
calls

```python
suggest_window(spec.variable, region=spec.region_key, today=date.today())
```

and previews `mode` + `reason` ("aligned to California fire season
(May–Oct)"), with Apply keeping the user's explicit edits authoritative
(the engine never overrides typed dates). The step-6 scheduled-generation
ticker (`survey-schedule`) can call `suggest_window` per run so recurring
jobs re-frame to the current season automatically (fire season rolls year
to year; the trailing event-density window re-sizes).

## 3. ops — `ops/daily_map_reel.py` REELS config

**Call sites:** the `REELS` dict (line 46) with per-reel `"window":
("trailing", N)` tuples, resolved by `_window(defn, today)` (line ~97)
and consumed by `build_spec(VizSpec, key, today)` (line ~100).

**Integration point:** allow a reel definition to declare
`"timescale": {"variable": ..., "region": ..., "intent": ...}`; in
`_window`, when present, call

```python
sug = suggest_window(variable, region=region_key, intent=intent, today=today)
```

instead of the fixed trailing-N window. Concrete upgrades this enables:
`earthquakes` → band-sized trailing window instead of hardcoded 7 days;
`hurricanes` → Atlantic season alignment instead of trailing 30 days;
`sea-ice` → melt-season (Jun–Sep) framing instead of trailing 7 days.
The `reason` string drops straight into the reel label/footer.

## 4. survey-derive / survey-cache / survey-schedule

- **survey-derive** climatologies need multi-year baselines: `trend`-mode
  suggestions give the fetch window for baseline construction.
- **survey-cache** fingerprinting (reel-studio v0.8.0) can hash the
  suggestion's `(start, end, mode, reason)` alongside the spec, so a
  re-framed window correctly invalidates cached frames.
- **survey-schedule** jobs gain a `timescale` field mirroring the REELS
  integration: each tick re-suggests before generating.

## Versioning note

The registry is data: additive entries (new regions, new seasons) are
minor bumps; changing an existing bound or band is a minor bump with a
CHANGELOG entry; removing/renaming a mode is major. Detection math
changes are minor with a CHANGELOG entry; the public function signatures
are stable.
