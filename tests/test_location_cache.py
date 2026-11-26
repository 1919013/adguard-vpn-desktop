from __future__ import annotations

import json

from core.servers import (
    load_location_cache,
    load_refresh_interval,
    parse_locations,
    save_location_cache,
    save_refresh_interval,
)


def sample_output():
    return (
        "ISO   COUNTRY              CITY                           PING ESTIMATE\n"
        "FI    Finland              Helsinki                       44\n"
        "EE    Estonia              Tallinn                        65\n"
    )


def test_parse_cli_locations():
    locations = parse_locations(sample_output())
    assert [item["city"] for item in locations] == ["Helsinki", "Tallinn"]
    assert locations[1]["iso"] == "EE"
    assert locations[1]["ping"] == 65


def test_location_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    locations = parse_locations(sample_output())
    assert save_location_cache(locations, "2026-11-26T17:00:00+00:00")
    loaded, updated_at = load_location_cache()
    assert loaded == locations
    assert updated_at == "2026-11-26T17:00:00+00:00"
    cache_file = tmp_path / "adguard-vpn-desktop" / "locations.json"
    assert json.loads(cache_file.read_text())["schema"] == 1


def test_empty_or_invalid_refresh_does_not_replace_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    original = parse_locations(sample_output())
    assert save_location_cache(original, "old")
    assert not save_location_cache([], "new")
    assert not save_location_cache([{"city": "broken"}], "new")
    loaded, updated_at = load_location_cache()
    assert loaded == original
    assert updated_at == "old"


def test_refresh_interval_defaults_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert load_refresh_interval() == 30
    assert save_refresh_interval(60)
    assert load_refresh_interval() == 60
    assert not save_refresh_interval(15)
    assert load_refresh_interval() == 60
