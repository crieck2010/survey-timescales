"""Console entry point: ``survey-timescales``.

Commands:
    suggest   suggest a [start, end] window for a variable/region
    registry  list the seeded timeframe registry entries

The ``--series`` CSV for ``suggest`` accepts three shapes (documented in
docs/API.md):

1. one column of numbers          -> value series (``--dt-days`` spacing,
                                     trailing at --today)
2. one column of dates/timestamps -> event timestamps
3. two columns: date,value        -> values with explicit dates
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys

from . import __version__
from .framing import suggest_window
from .registry import (StaticVariableError, UnknownVariableError,
                       load_registry)

_VALID_INTENTS = ("cycle", "season", "event-density", "trend")


def _parse_csv(path: str, dt_days: float):
    """Return (kind, payload) mirroring framing._parse_series conventions."""
    dates, values = [], []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = [[c.strip() for c in row] for row in reader if row and any(c.strip() for c in row)]
    # Tolerate a header row: if the first row fails to parse as data, drop it.
    def _looks_like_data(row):
        try:
            _parse_cell(row[0])
            if len(row) > 1:
                float(row[1])
            return True
        except ValueError:
            return False

    if rows and not _looks_like_data(rows[0]):
        rows = rows[1:]
    if not rows:
        raise ValueError(f"{path}: no data rows found")

    if len(rows[0]) >= 2:
        pairs = []
        for row in rows:
            pairs.append((_parse_cell(row[0]), float(row[1])))
        return "pairs", pairs
    cells = [_parse_cell(r[0]) for r in rows]
    if all(isinstance(c, _dt.date) for c in cells):
        return "events", cells
    return "values", [float(c) for c in cells]


def _parse_cell(cell: str):
    cell = cell.strip()
    try:
        return float(cell)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return _dt.datetime.strptime(cell, fmt).date()
        except ValueError:
            continue
    try:
        return _dt.date.fromisoformat(cell)
    except ValueError:
        raise ValueError(f"cannot parse CSV cell {cell!r} as a number or date")


def _cmd_suggest(args) -> int:
    today = _dt.date.fromisoformat(args.today) if args.today else None
    series = None
    if args.series:
        kind, payload = _parse_csv(args.series, args.dt_days)
        if kind == "events":
            series = payload
        elif kind == "values":
            series = payload  # framing treats a numeric list as trailing values
        else:  # pairs -> list of (date, value)
            series = payload
    try:
        sug = suggest_window(
            args.variable,
            region=args.region,
            series=series,
            intent=args.intent,
            today=today,
            source=args.source,
            dt_days=args.dt_days,
        )
    except (UnknownVariableError, StaticVariableError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(sug.to_dict(), indent=2, default=str))
    else:
        print(f"start:  {sug.start.isoformat()}")
        print(f"end:    {sug.end.isoformat()}")
        print(f"mode:   {sug.mode}")
        print(f"reason: {sug.reason}")
    return 0


def _cmd_registry(args) -> int:
    reg = load_registry()
    entries = reg.entries
    if args.variable:
        var = args.variable.strip().lower()
        entries = [e for e in entries if e.variable == var]
        if not entries:
            print(f"error: unknown variable {args.variable!r}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps([e.to_dict() for e in entries], indent=2, default=str))
        return 0
    for e in entries:
        region = e.region or "(global)"
        if e.static:
            desc = "static underlay — n/a"
        elif e.default_mode == "cycle":
            desc = f"cycle {e.cycle_period_days:g}d"
        elif e.default_mode == "season" and e.season:
            s = e.season
            desc = (f"season {s.get('name')} "
                    f"({s['start_month']:02d}-{s['start_day']:02d}.."
                    f"{s['end_month']:02d}-{s['end_day']:02d})")
        elif e.default_mode == "event-density" and e.event_density:
            b = e.event_density
            desc = (f"event-density {b['min_count']}-{b['max_count']} events / "
                    f"{b['min_window_days']}-{b['max_window_days']}d")
        elif e.default_mode == "trend":
            desc = f"trend {e.trend_years:g}yr"
        else:
            desc = e.default_mode
        print(f"{e.variable:14s} {region:20s} {e.source:12s} {desc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="survey-timescales",
        description="Timeframe-selection engine for the survey remote-sensing suite.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("suggest", help="suggest a [start, end] window")
    s.add_argument("--variable", required=True, help="canonical variable key, e.g. fire")
    s.add_argument("--region", default=None, help="gazetteer region key, e.g. california")
    s.add_argument("--intent", default=None, choices=_VALID_INTENTS,
                   help="force a framing mode")
    s.add_argument("--source", default=None,
                   help="disambiguate multi-source variables (e.g. tp -> era5/imerg)")
    s.add_argument("--series", default=None, metavar="data.csv",
                   help="CSV: one column of values, one column of timestamps, or date,value pairs")
    s.add_argument("--dt-days", type=float, default=1.0,
                   help="sample spacing in days for a single-column value series")
    s.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                   help="reference date (default: today)")
    s.add_argument("--json", action="store_true", help="emit JSON")
    s.set_defaults(func=_cmd_suggest)

    r = sub.add_parser("registry", help="list seeded registry entries")
    r.add_argument("--variable", default=None, help="filter to one variable")
    r.add_argument("--json", action="store_true", help="emit JSON")
    r.set_defaults(func=_cmd_registry)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
