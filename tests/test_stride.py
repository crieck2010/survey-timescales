"""Tests for timescales.recommend_stride (phenomenon-aware stride)."""

import importlib
import sys

import pytest

import timescales


EXPECTED = {
    "tide": {"stride_days": 1, "stride_hours": 3, "forecast_hours": None},
    "synoptic": {"stride_days": 1, "stride_hours": 6,
                 "forecast_hours": (0, 6, 12, 18)},
    "seasonal": {"stride_days": 7, "stride_hours": 0, "forecast_hours": None},
    "climate": {"stride_days": 30, "stride_hours": 0, "forecast_hours": None},
    "event": {"per_event": True, "stride_days": 1, "stride_hours": 0,
              "forecast_hours": None},
}


def test_recommend_stride_exported():
    assert "recommend_stride" in timescales.__all__
    assert timescales.recommend_stride is timescales.stride.recommend_stride


@pytest.mark.parametrize("phenomenon, expected", list(EXPECTED.items()))
def test_each_phenomenon_values(phenomenon, expected):
    out = timescales.recommend_stride(phenomenon)
    for key, value in expected.items():
        assert out[key] == value, (phenomenon, key, out[key], value)
    assert out["phenomenon"] == phenomenon
    assert out["source"] is None
    assert isinstance(out["reason"], str) and out["reason"]
    # "via" distinguishes the autopilot peer from the built-in fallback
    assert out["via"] in ("autopilot", "builtin-fallback")


def test_via_autopilot_with_peer_installed():
    # survey-autopilot is installed in this venv, so the peer wins.
    pytest.importorskip("autopilot.stride")
    out = timescales.recommend_stride("synoptic", source="gfs-wind")
    assert out["via"] == "autopilot"
    assert out["source"] == "gfs-wind"
    assert out["forecast_hours"] == (0, 6, 12, 18)


def test_fallback_path_returns_same_values(monkeypatch):
    # Hide the peer: the lazy import inside recommend_stride then falls
    # back to the built-in mirrored table.
    monkeypatch.setitem(sys.modules, "autopilot", None)
    monkeypatch.setitem(sys.modules, "autopilot.stride", None)
    for phenomenon, expected in EXPECTED.items():
        out = timescales.recommend_stride(phenomenon)
        assert out["via"] == "builtin-fallback"
        for key, value in expected.items():
            assert out[key] == value, (phenomenon, key)
        assert out["phenomenon"] == phenomenon
        assert isinstance(out["reason"], str) and out["reason"]


def test_fallback_reason_strings_match_autopilot_docs(monkeypatch):
    # Fallback reason strings are copied verbatim from autopilot's table.
    from autopilot.stride import STRIDE_TABLE
    monkeypatch.setitem(sys.modules, "autopilot", None)
    monkeypatch.setitem(sys.modules, "autopilot.stride", None)
    for phenomenon in EXPECTED:
        out = timescales.recommend_stride(phenomenon)
        assert out["reason"] == STRIDE_TABLE[phenomenon]["reason"]


def test_unknown_phenomenon_raises(monkeypatch):
    for via in ("autopilot", "builtin-fallback"):
        if via == "builtin-fallback":
            monkeypatch.setitem(sys.modules, "autopilot", None)
            monkeypatch.setitem(sys.modules, "autopilot.stride", None)
        with pytest.raises(ValueError) as excinfo:
            timescales.recommend_stride("thermonuclear")
        msg = str(excinfo.value)
        for key in ("tide", "synoptic", "seasonal", "climate", "event"):
            assert key in msg
    monkeypatch.undo()


def test_event_reason_mentions_event_list():
    out = timescales.recommend_stride("event")
    assert out["per_event"] is True
    assert "event" in out["reason"].lower()
