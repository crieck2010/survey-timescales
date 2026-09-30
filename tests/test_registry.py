"""Registry tests: coverage of all 13 suite data sources, seasons, errors."""

import pytest

from timescales.registry import (StaticVariableError, UnknownVariableError,
                                 canonical_variable, load_registry)


@pytest.fixture(scope="module")
def reg():
    return load_registry(_reload=True)


# (variable, source) pairs for the 13 suite data sources (+ static underlays).
EXPECTED_SOURCES = {
    "sst": "oisst",
    "t2m": "era5", "wind": "era5", "msl": "era5",
    "tp": "era5",  # + imerg below
    "currents": "oscar",
    "fire": "firms",
    "sea-ice": "nsidc",
    "night-lights": "blackmarble",
    "storm-tracks": "ibtracs",
    "water-storage": "grace",
    "streamflow": "usgs",
    "ocean-color": "oceancolor",
    "earthquakes": "comcat",
}


def test_all_suite_sources_present(reg):
    for variable, source in EXPECTED_SOURCES.items():
        entry = reg.find(variable, source=source)
        assert entry.source == source, variable
    # tp exists under both ERA5 and IMERG, disambiguated by source
    era5 = reg.find("tp", source="era5")
    imerg = reg.find("tp", source="imerg")
    assert era5 is not imerg
    assert era5.trend_years != imerg.trend_years


def test_gebco_marked_static_na(reg):
    for variable in ("bathymetry", "elevation"):
        entry = next(e for e in reg.entries if e.variable == variable)
        assert entry.static is True
        assert entry.modes == ("na",)
        with pytest.raises(StaticVariableError):
            reg.find(variable)


def test_legacy_alias(reg):
    assert canonical_variable("chlorophyll") == "ocean-color"
    assert reg.find("chlorophyll").variable == "ocean-color"


def test_region_lookup_and_global_fallback(reg):
    regional = reg.find("fire", region="california")
    assert regional.region == "california"
    assert regional.default_mode == "season"
    assert regional.season is not None
    # unknown region falls back to the variable's global default
    glob = reg.find("fire", region="somewhere-else")
    assert glob.region is None
    assert glob.default_mode == "event-density"


def test_season_entries_have_basis(reg):
    seasons = [e for e in reg.entries if e.season]
    assert len(seasons) >= 8  # fire x5, storm-tracks x5, sea-ice, ocean-color
    for e in seasons:
        s = e.season
        assert s.get("name"), e.variable
        assert s.get("basis"), (e.variable, e.region)
        assert 1 <= s["start_month"] <= 12 and 1 <= s["end_month"] <= 12


def test_entry_invariants(reg):
    assert len(reg.entries) >= 20
    for e in reg.entries:
        assert e.variable and e.source
        assert e.default_mode in e.modes, e.variable
        if not e.static:
            assert "na" not in e.modes


def test_unknown_variable_lists_known(reg):
    with pytest.raises(UnknownVariableError) as exc:
        reg.find("bogus-variable")
    assert "sst" in str(exc.value)


def test_unknown_source_suggests_known(reg):
    with pytest.raises(UnknownVariableError) as exc:
        reg.find("tp", source="bogus")
    assert "era5" in str(exc.value) and "imerg" in str(exc.value)


def test_yaml_subset_parser_matches_pyyaml():
    yaml = pytest.importorskip("yaml")
    from timescales.registry import REGISTRY_PATH, _load_subset_yaml
    with open(REGISTRY_PATH, encoding="utf-8") as fh:
        text = fh.read()
    mine = _load_subset_yaml(text)["entries"]
    theirs = yaml.safe_load(text)["entries"]
    assert len(mine) == len(theirs)
    for m, t in zip(mine, theirs):
        assert m["variable"] == t["variable"]
        assert (m["region"] or None) == t["region"]
        assert m["source"] == t["source"]
        assert list(m["modes"]) == list(t["modes"])
        assert m["default_mode"] == t["default_mode"]
        if m.get("season"):
            assert m["season"]["name"] == t["season"]["name"]
            assert m["season"]["basis"] == t["season"]["basis"]
        if m.get("event_density"):
            assert m["event_density"] == t["event_density"]
