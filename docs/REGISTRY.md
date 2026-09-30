# Registry

The full seeded timeframe table (`src/timescales/data/timescales.yaml`),
with the basis for every entry and every season bound.

Conventions: `variable` uses the canonical survey-viz keys (spec.py
`KNOWN_VARIABLES`; `chlorophyll` is the legacy alias of `ocean-color`);
`region` uses the survey-viz gazetteer keys (`null` = global default);
`source` uses the survey-viz adapter keys. `tp` exists under two sources —
pass `source=` to disambiguate.

## Cycle / trend variables

| variable | region | source | default | cycle (d) | trend (yr) | trend basis |
|---|---|---|---|---|---|---|
| sst | global | oisst | cycle | 365.25 | 40 | NOAA OISST 1981–present |
| t2m | global | era5 | cycle | 365.25 | 30 | ERA5 1940–present; 30 yr = WMO normal |
| wind | global | era5 | cycle | 365.25 | 30 | ERA5 1940–present |
| msl | global | era5 | cycle | 365.25 | 30 | ERA5 1940–present |
| tp | global | era5 | cycle | 365.25 | 30 | ERA5 1940–present |
| tp | global | imerg | cycle | 365.25 | 25 | IMERG 2000–present |
| currents | global | oscar | cycle | 365.25 | 20 | OSCAR 1992–present |
| sea-ice | global | nsidc | cycle | 365.25 | 40 | NSIDC Oct 1978–present |
| night-lights | global | blackmarble | **trend** | 365.25 | 12 | VIIRS DNB 2012–present |
| water-storage | global | grace | cycle | 365.25 | 20 | GRACE/GRACE-FO 2002–present (2017–18 gap) |
| streamflow | global | usgs | cycle | 365.25 | 30 | USGS NWIS; 30 yr = WMO normal |
| ocean-color | global | oceancolor | cycle | 365.25 | 20 | MODIS Aqua R2022 2002–present |

Notes: `wind` carries a note that trade-wind/monsoon regions show a
semi-annual (182.6 d) harmonic — data-driven detection picks it up when a
series is supplied. `sea-ice`'s registry melt season is Arctic; for
`southern-ocean` the annual cycle holds but the melt window is inverted —
callers should pass a series or explicit dates there.

## Event variables (event-density bands)

| variable | region | default | band (events) | window caps (d) | lull thr./day |
|---|---|---|---|---|---|
| fire | global | event-density | 50–500 (target 200) | 7–180 | 1.0 |
| storm-tracks | global | event-density | 10–100 (target 40) | 30–365 | 0.1 |
| earthquakes | global | event-density | 20–200 (target 60) | 1–365 | 0.1 |

Bands are readability heuristics for vertical reels, not completeness
claims. `earthquakes` trend horizon is 50 yr (ComCat reasonably complete
for M≥5 since the 1960s); `storm-tracks` trend horizon is 40 yr (IBTrACS
v4 geostationary era, early 1980s+).

## Season bounds and their basis

| variable | region | season name | bounds | basis |
|---|---|---|---|---|
| fire | california | California fire season | May 1 – Oct 31 | CAL FIRE historical incident record: large-fire activity concentrates May–October (peak Aug–Sep) |
| fire | pacific-northwest | Pacific Northwest fire season | May 1 – Oct 31 | Northwest Interagency Coordination Center (NWCC): PNW fire activity concentrates May–October |
| fire | boreal-canada | Boreal Canada fire season | May 1 – Sep 30 | Canadian Interagency Forest Fire Centre (CIFFC): boreal fire activity runs May–September |
| fire | amazon-basin | Amazon burning season | Jul 1 – Nov 30 | INPE Queimadas program: Amazon fire counts peak in the dry season, July–November (peak Aug–Sep) |
| fire | australia-southeast | Southeast Australia fire season | Oct 1 – Mar 31 (wraps) | Australian Bureau of Meteorology / AFAC: southeast Australia's bushfire season runs October–March |
| sea-ice | global (Arctic) | Arctic melt season | Jun 1 – Sep 30 | NSIDC Arctic Sea Ice News: melt season June–September, September minimum |
| storm-tracks | north-atlantic | Atlantic hurricane season | Jun 1 – Nov 30 | National Hurricane Center (NHC): official Atlantic hurricane season |
| storm-tracks | caribbean-sea | Atlantic hurricane season | Jun 1 – Nov 30 | NHC official season (same basin) |
| storm-tracks | gulf-of-mexico | Atlantic hurricane season | Jun 1 – Nov 30 | NHC official season (same basin) |
| storm-tracks | us-east-coast | Atlantic hurricane season | Jun 1 – Nov 30 | NHC official season (same basin) |
| storm-tracks | north-pacific | Western North Pacific typhoon season | May 1 – Nov 30 | JMA operational convention: WNP typhoon season monitored May–November (activity is year-round, concentrates in this band) |
| ocean-color | north-atlantic | North Atlantic spring bloom | Mar 1 – Jun 30 | MODIS-Aqua ocean-color climatology: spring bloom typically develops March–June (timing shifts year to year) |

All season bounds are **climatological approximations** — individual years
shift (early/late onset, off-season events). The engine frames the typical
season; it does not adapt to a specific year's anomaly.

## Static underlays (n/a)

| variable | source | handling |
|---|---|---|
| bathymetry | gebco | `static: true` — `suggest_window` raises `StaticVariableError` |
| elevation | gebco | `static: true` — `suggest_window` raises `StaticVariableError` |

GEBCO grids are time-invariant cartographic underlays: no window applies.

## Lookup precedence

`(variable, region, source)` → `(variable, region)` → `(variable, global
default)`. A region-specific season (e.g. California fire) beats the
global event-density default; an unknown region falls back to the global
entry; an unknown variable raises `UnknownVariableError` listing the known
variables rather than guessing.
