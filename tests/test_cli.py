"""CLI smoke tests: suggest / registry, CSV series shapes, error paths."""

import json

import pytest

from timescales.cli import main


def _run(argv, capsys):
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_suggest_season(capsys):
    code, out, _ = _run(["suggest", "--variable", "fire", "--region", "california",
                         "--today", "2026-09-30"], capsys)
    assert code == 0
    assert "start:  2026-05-01" in out
    assert "mode:   season" in out
    assert "California fire season" in out


def test_suggest_json(capsys):
    code, out, _ = _run(["suggest", "--variable", "sst", "--today", "2026-09-30",
                         "--json"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["mode"] == "cycle"
    assert doc["start"] == "2025-09-30"


def test_suggest_unknown_variable_fails(capsys):
    code, _, err = _run(["suggest", "--variable", "bogus"], capsys)
    assert code == 2
    assert "Unknown variable" in err


def test_suggest_static_variable_fails(capsys):
    code, _, err = _run(["suggest", "--variable", "bathymetry"], capsys)
    assert code == 2
    assert "time-invariant" in err


def test_suggest_intent_override(capsys):
    code, out, _ = _run(["suggest", "--variable", "fire", "--intent", "trend",
                         "--today", "2026-09-30"], capsys)
    assert code == 0
    assert "mode:   trend" in out


def test_suggest_series_values_csv(tmp_path, capsys):
    p = tmp_path / "vals.csv"
    p.write_text("value\n" + "\n".join(["1.0"] * 400) + "\n")
    code, out, _ = _run(["suggest", "--variable", "sst", "--series", str(p),
                         "--today", "2026-09-30"], capsys)
    assert code == 0
    assert "mode:   cycle" in out


def test_suggest_series_events_csv(tmp_path, capsys):
    p = tmp_path / "events.csv"
    p.write_text("timestamp\n2026-09-01\n2026-09-10\n2026-09-20\n")
    code, out, _ = _run(["suggest", "--variable", "earthquakes",
                         "--series", str(p), "--today", "2026-09-30"], capsys)
    assert code == 0
    assert "mode:   event-density" in out


def test_suggest_series_pairs_csv(tmp_path, capsys):
    p = tmp_path / "pairs.csv"
    rows = [f"2026-09-{d:02d},{v}" for d, v in
            [(1, 0.0), (10, 5.0), (20, 3.0), (30, 0.0)]]
    p.write_text("date,value\n" + "\n".join(rows) + "\n")
    code, out, _ = _run(["suggest", "--variable", "fire", "--region", "california",
                         "--intent", "event-density", "--series", str(p),
                         "--today", "2026-09-30"], capsys)
    assert code == 0
    assert "mode:   event-density" in out


def test_registry_lists_entries(capsys):
    code, out, _ = _run(["registry"], capsys)
    assert code == 0
    assert "sst" in out and "fire" in out and "storm-tracks" in out


def test_registry_filter_variable(capsys):
    code, out, _ = _run(["registry", "--variable", "fire"], capsys)
    assert code == 0
    assert "california" in out
    assert "storm-tracks" not in out


def test_registry_json(capsys):
    code, out, _ = _run(["registry", "--variable", "sst", "--json"], capsys)
    assert code == 0
    docs = json.loads(out)
    assert len(docs) == 1 and docs[0]["source"] == "oisst"


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
