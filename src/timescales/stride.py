"""Phenomenon-aware stride recommendation: how finely should frames be spaced?

The engine *recommends*; callers decide (same "suggests; callers decide"
contract as :func:`timescales.suggest_window`). The stride is a physics
decision, not a rendering detail: sampling tides daily aliases the ~12.4 h
constituents into nonsense; sampling the seasonal cycle 6-hourly wastes
frames on mud. The right stride follows the phenomenon's dominant timescale.

Delegation: when the ``survey-autopilot`` engine is importable, this module
delegates to ``autopilot.stride.recommend_stride`` — the canonical table
lives there. Otherwise it falls back to a built-in table mirrored from
survey-autopilot's documented table (install survey-autopilot for the
canonical one). The returned dict always carries ``"via"`` so callers can
tell which source produced the recommendation.
"""

from __future__ import annotations

from typing import Optional

#: Built-in fallback stride table, mirrored from survey-autopilot's
#: documented table (autopilot.stride.STRIDE_TABLE). The reason strings are
#: copied verbatim; install survey-autopilot for the canonical table.
#: stride_days/stride_hours are the recommended frame spacing;
#: forecast_hours lists the GFS forecast hours to sample (GFS only).
_FALLBACK_TABLE = {
    "tide": {
        "stride_days": 1,
        "stride_hours": 3,
        "forecast_hours": None,
        "reason": (
            "tidal constituents (~12.4h) need sub-daily sampling to stay legible; "
            "3-hourly resolves the semidiurnal cycle without aliasing"
        ),
    },
    "synoptic": {
        "stride_days": 1,
        "stride_hours": 6,
        "forecast_hours": (0, 6, 12, 18),
        "reason": (
            "synoptic-scale wind/storm evolution at 6-hourly; forecast_hours "
            "applies to GFS-wind sources only"
        ),
    },
    "seasonal": {
        "stride_days": 7,
        "stride_hours": 0,
        "forecast_hours": None,
        "reason": (
            "weekly sampling resolves the seasonal cycle without mud — denser "
            "sampling adds frames but no new information"
        ),
    },
    "climate": {
        "stride_days": 30,
        "stride_hours": 0,
        "forecast_hours": None,
        "reason": (
            "monthly sampling for multi-year climate context; sub-monthly "
            "variation is noise at this timescale"
        ),
    },
    "event": {
        "per_event": True,
        "stride_days": 1,
        "stride_hours": 0,
        "forecast_hours": None,
        "reason": (
            "event-driven: one frame per event, not a fixed cadence — the "
            "stride is informational, the event list drives the frames"
        ),
    },
}

_VALID_KEYS = tuple(sorted(_FALLBACK_TABLE))


def _delegate():
    """Return autopilot's recommend_stride if the peer is importable."""
    try:
        from autopilot.stride import recommend_stride as _ap_rs
    except ImportError:
        return None
    return _ap_rs


def recommend_stride(phenomenon: str, source: Optional[str] = None) -> dict:
    """Recommend a frame stride for a phenomenon.

    The engine *recommends*; callers decide — the returned dict is a starting
    point, not a law. A storm that stalls needs denser sampling than
    "synoptic" assumes; the caller owns deviations.

    Args:
        phenomenon: one of "tide", "synoptic", "seasonal", "climate",
            "event".
        source: optional source name (e.g. "gfs-wind"). Informational —
            recorded in the output for future source-specific overrides,
            no behavior change yet. Note "forecast_hours" is GFS-wind
            specific (the GFS NOMADS feed publishes f000..f120); it is None
            for everything else and should be ignored for non-GFS sources.

    Returns:
        {"phenomenon", "stride_days", "stride_hours", "forecast_hours",
         "reason", "via"} plus "per_event": True for "event", plus "source"
        echoing the input. "via" is "autopilot" when the survey-autopilot
        peer produced the recommendation, "builtin-fallback" when the
        built-in mirrored table did.

    Raises:
        ValueError: for unknown phenomena, listing the valid keys — on
            BOTH the autopilot path and the fallback path. Guessing a
            stride for an unknown phenomenon would be worse than failing.
    """
    if phenomenon not in _FALLBACK_TABLE:
        valid = ", ".join(_VALID_KEYS)
        raise ValueError(
            f"unknown phenomenon {phenomenon!r}; valid keys: {valid}"
        )
    _ap_rs = _delegate()
    if _ap_rs is not None:
        out = _ap_rs(phenomenon, source=source)
        out["via"] = "autopilot"
        return out
    out = {"phenomenon": phenomenon, "source": source}
    out.update(_FALLBACK_TABLE[phenomenon])
    out["via"] = "builtin-fallback"
    return out
