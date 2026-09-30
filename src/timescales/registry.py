"""Timeframe registry for the survey remote-sensing suite.

The registry is curated data shipped with the package (``data/timescales.yaml``):
no network, no LLM, fully deterministic. It maps a (variable, region, source)
triple to the characteristic timescales a sensible map-reel window is built
from: dominant cycles, climatological season bounds, trend horizons, and
event-density bands.

YAML parsing is a deliberate, documented YAML *subset* parser (stdlib only).
It handles exactly the constructs used by ``timescales.yaml``:

* block mappings (``key: value``) nested by indentation,
* block sequences (``- item``) whose items are mappings,
* flow sequences (``[a, b, c]``) and flow mappings (``{k: v, ...}``),
* scalars: quoted strings, ints, floats, ``null``/``~``, ``true``/``false``,
* ``#`` comments.

Deliberate deviation from YAML 1.1: ``y``/``n``/``yes``/``no``/``on``/``off``
are NOT coerced to booleans, so the registry's ``na`` (not-applicable) mode
stays the string ``"na"``. Only ``true``/``false`` (any case) become booleans
and ``null``/``~``/empty become ``None``. Anchors, tags, multi-line scalars,
and explicit document markers are not supported and raise ``ValueError``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "RegistryEntry",
    "TimescaleRegistry",
    "load_registry",
    "canonical_variable",
    "UnknownVariableError",
    "StaticVariableError",
    "REGISTRY_PATH",
]

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "data", "timescales.yaml")

#: Legacy variable names canonicalized before registry lookup (mirrors
#: survey-viz's VizSpec alias handling).
_VARIABLE_ALIASES = {"chlorophyll": "ocean-color"}


def canonical_variable(variable: str) -> str:
    """Canonicalize a variable key (lowercase, legacy aliases resolved)."""
    v = str(variable).strip().lower()
    return _VARIABLE_ALIASES.get(v, v)


class UnknownVariableError(ValueError):
    """Raised when no registry entry exists for a variable (or combination)."""


class StaticVariableError(ValueError):
    """Raised when a timeframe is requested for a time-invariant underlay."""


# ---------------------------------------------------------------------------
# Minimal YAML-subset parser (see module docstring for the supported subset)
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(
    r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$"
)


def _strip_comment(line: str) -> str:
    in_s = in_d = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            if i == 0 or line[i - 1] in " \t":
                return line[:i]
    return line


def _bracket_balance(line: str) -> int:
    """Net unclosed ``{[()]}`` depth of a line, ignoring quoted spans."""
    in_s = in_d = depth = 0
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif not in_s and not in_d:
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
    return depth


def _lex_lines(text: str) -> List[Tuple[int, str]]:
    lines: List[Tuple[int, str]] = []
    buf = ""
    for raw in text.splitlines():
        if raw.strip().startswith("&") or raw.strip().startswith("*"):
            raise ValueError("YAML anchors/aliases are not supported by the subset parser")
        if raw.strip().startswith("---") or raw.strip().startswith("..."):
            raise ValueError("YAML document markers are not supported by the subset parser")
        if not buf and not raw.strip():
            continue
        buf = (buf + " " + raw.strip()) if buf else raw
        if _bracket_balance(buf) > 0:
            continue  # multi-line flow collection: keep joining
        line = _strip_comment(buf)
        buf = ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    if buf:
        raise ValueError(f"Unbalanced brackets in: {buf!r}")
    return lines


def _split_top_level(text: str, sep: str) -> List[str]:
    """Split on ``sep`` characters that are not inside quotes/braces/brackets."""
    parts, depth, in_s, in_d, cur = [], 0, False, False, []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_d:
            in_s = not in_s
            cur.append(ch)
        elif ch == '"' and not in_s:
            in_d = not in_d
            cur.append(ch)
        elif not in_s and not in_d and ch in "[{":
            depth += 1
            cur.append(ch)
        elif not in_s and not in_d and ch in "]}":
            depth -= 1
            cur.append(ch)
        elif not in_s and not in_d and depth == 0 and ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        inner = text[1:-1]
        if text[0] == '"':
            inner = (inner.replace('\\"', '"').replace("\\\\", "\\")
                          .replace("\\n", "\n").replace("\\t", "\t"))
        return inner
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p) for p in _split_top_level(inner, ",")]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        d: Dict[str, Any] = {}
        if inner:
            for part in _split_top_level(inner, ","):
                k, _, v = part.partition(":")
                d[k.strip().strip("'\"")] = _parse_scalar(v)
        return d
    low = text.lower()
    if low in ("null", "~", "none", ""):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _split_key(text: str) -> Tuple[str, str]:
    """Split a mapping line into (key, rest) on the first top-level colon."""
    in_s = in_d = False
    depth = 0
    for i, ch in enumerate(text):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif not in_s and not in_d:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1] in " \t"):
                return text[:i].strip().strip("'\""), text[i + 1:].strip()
    raise ValueError(f"Not a mapping line: {text!r}")


def _parse_block(lines: List[Tuple[int, str]], pos: int, indent: int):
    first_text = lines[pos][1]
    if first_text == "-" or first_text.startswith("- "):
        return _parse_list(lines, pos, indent)
    return _parse_map(lines, pos, indent)


def _parse_list(lines: List[Tuple[int, str]], pos: int, indent: int):
    items: List[Any] = []
    while pos < len(lines):
        ind, text = lines[pos]
        if ind != indent or not (text == "-" or text.startswith("- ")):
            break
        content = text[1:].strip()
        pos += 1
        if not content:
            if pos < len(lines) and lines[pos][0] > indent:
                val, pos = _parse_block(lines, pos, lines[pos][0])
            else:
                val = None
            items.append(val)
        else:
            # "- key: value" — treat as a mapping whose first line is the
            # inline content, rendered at a virtual deeper indent. Only the
            # leading run of deeper-indented lines belongs to this item.
            run = []
            for i2, t2 in lines[pos:]:
                if i2 > indent:
                    run.append((i2, t2))
                else:
                    break
            virtual = [(indent + 2, content)] + run
            val, _ = _parse_map(virtual, 0, indent + 2)
            pos += len(run)
            items.append(val)
    return items, pos


def _parse_map(lines: List[Tuple[int, str]], pos: int, indent: int):
    d: Dict[str, Any] = {}
    while pos < len(lines):
        ind, text = lines[pos]
        if ind != indent or text == "-" or text.startswith("- "):
            break
        key, rest = _split_key(text)
        pos += 1
        if rest == "":
            if pos < len(lines) and lines[pos][0] > indent:
                val, pos = _parse_block(lines, pos, lines[pos][0])
            elif (pos < len(lines) and lines[pos][0] == indent
                  and (lines[pos][1] == "-"
                       or lines[pos][1].startswith("- "))):
                # Same-indent block sequence (valid YAML, used by the
                # registry's top-level "entries:" key).
                val, pos = _parse_list(lines, pos, indent)
            else:
                val = None
        else:
            val = _parse_scalar(rest)
        d[key] = val
    return d, pos


def _load_subset_yaml(text: str) -> Any:
    lines = _lex_lines(text)
    if not lines:
        return None
    val, pos = _parse_block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise ValueError(f"Trailing unparsed lines at line index {pos}")
    return val


# ---------------------------------------------------------------------------
# Registry entries
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ("variable", "source", "modes", "default_mode")


@dataclass(frozen=True)
class RegistryEntry:
    """One curated timeframe record for a (variable, region, source) triple."""

    variable: str
    region: Optional[str]
    source: str
    long_name: str = ""
    modes: Tuple[str, ...] = ()
    default_mode: str = ""
    static: bool = False
    cycle_period_days: Optional[float] = None
    cycle_basis: Optional[str] = None
    cadence_days: Optional[float] = None
    season: Optional[Dict[str, Any]] = None
    trend_years: Optional[float] = None
    trend_basis: Optional[str] = None
    event_density: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable": self.variable,
            "region": self.region,
            "source": self.source,
            "long_name": self.long_name,
            "modes": list(self.modes),
            "default_mode": self.default_mode,
            "static": self.static,
            "cycle_period_days": self.cycle_period_days,
            "cycle_basis": self.cycle_basis,
            "cadence_days": self.cadence_days,
            "season": dict(self.season) if self.season else None,
            "trend_years": self.trend_years,
            "trend_basis": self.trend_basis,
            "event_density": dict(self.event_density) if self.event_density else None,
            "notes": self.notes,
        }


@dataclass
class TimescaleRegistry:
    """The loaded registry: entry list plus (variable, region, source) lookup."""

    entries: List[RegistryEntry] = field(default_factory=list)

    def find(self, variable: str, region: Optional[str] = None,
             source: Optional[str] = None) -> RegistryEntry:
        """Look up the entry for ``(variable, region[, source])``.

        Precedence: exact (variable, region, source) -> (variable, region) ->
        (variable, global). Raises :class:`UnknownVariableError` when nothing
        matches, :class:`StaticVariableError` for time-invariant underlays.
        """
        variable = canonical_variable(variable)
        region = str(region).strip().lower() if region else None
        source = str(source).strip().lower() if source else None

        cands = [e for e in self.entries if e.variable == variable]
        if not cands:
            raise UnknownVariableError(
                f"Unknown variable {variable!r}. Known variables: "
                + ", ".join(sorted({e.variable for e in self.entries}))
            )
        if source:
            cands = [e for e in cands if e.source == source]
            if not cands:
                known = sorted({e.source for e in self.entries
                                if e.variable == variable})
                raise UnknownVariableError(
                    f"Variable {variable!r} has no entry for source {source!r}. "
                    f"Known sources for {variable!r}: " + ", ".join(known)
                )
        if region:
            regional = [e for e in cands if e.region == region]
            if regional:
                entry = regional[0]
            else:
                entry = next((e for e in cands if e.region is None), None)
                if entry is None:
                    raise UnknownVariableError(
                        f"Variable {variable!r} has no entry for region "
                        f"{region!r} and no global default."
                    )
        else:
            entry = next((e for e in cands if e.region is None), cands[0])
        if entry.static:
            raise StaticVariableError(
                f"{entry.long_name or entry.variable!r} is a time-invariant "
                f"underlay ({entry.source}); no timeframe window applies (n/a)."
            )
        return entry

    def variables(self) -> List[str]:
        return sorted({e.variable for e in self.entries})


_registry_cache: Optional[TimescaleRegistry] = None


def load_registry(path: Optional[str] = None, *, _reload: bool = False) -> TimescaleRegistry:
    """Load the curated timeframe registry (cached; pass ``_reload=True`` to re-read)."""
    global _registry_cache
    if _registry_cache is not None and path is None and not _reload:
        return _registry_cache
    with open(path or REGISTRY_PATH, "r", encoding="utf-8") as fh:
        doc = _load_subset_yaml(fh.read())
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
        raise ValueError("Registry YAML must contain a top-level 'entries' list")
    entries: List[RegistryEntry] = []
    for i, raw in enumerate(doc["entries"]):
        for f in REQUIRED_FIELDS:
            if f not in raw:
                raise ValueError(f"Registry entry {i} is missing required field {f!r}")
        modes = raw["modes"]
        if isinstance(modes, str):
            modes = [modes]
        entries.append(RegistryEntry(
            variable=canonical_variable(raw["variable"]),
            region=(str(raw["region"]).strip().lower()
                    if raw.get("region") not in (None, "") else None),
            source=str(raw["source"]).strip().lower(),
            long_name=str(raw.get("long_name") or ""),
            modes=tuple(str(m) for m in modes),
            default_mode=str(raw["default_mode"]),
            static=bool(raw.get("static", False)),
            cycle_period_days=(float(raw["cycle_period_days"])
                               if raw.get("cycle_period_days") is not None else None),
            cycle_basis=raw.get("cycle_basis"),
            cadence_days=(float(raw["cadence_days"])
                          if raw.get("cadence_days") is not None else None),
            season=dict(raw["season"]) if raw.get("season") else None,
            trend_years=(float(raw["trend_years"])
                         if raw.get("trend_years") is not None else None),
            trend_basis=raw.get("trend_basis"),
            event_density=(dict(raw["event_density"])
                           if raw.get("event_density") else None),
            notes=raw.get("notes"),
        ))
    reg = TimescaleRegistry(entries=entries)
    if path is None and not _reload:
        _registry_cache = reg
    return reg
