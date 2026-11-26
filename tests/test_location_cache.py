from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class LocationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.env = patch.dict(os.environ, {"XDG_STATE_HOME": self.temp_dir.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_parse_cli_locations(self):
        locations = parse_locations(sample_output())
        self.assertEqual([item["city"] for item in locations], ["Helsinki", "Tallinn"])
        self.assertEqual(locations[1]["iso"], "EE")
        self.assertEqual(locations[1]["ping"], 65)

    def test_location_cache_round_trip(self):
        locations = parse_locations(sample_output())
        self.assertTrue(save_location_cache(locations, "2026-11-26T17:00:00+00:00"))
        loaded, updated_at = load_location_cache()
        self.assertEqual(loaded, locations)
        self.assertEqual(updated_at, "2026-11-26T17:00:00+00:00")
        cache_file = Path(self.temp_dir.name) / "adguard-vpn-desktop" / "locations.json"
        self.assertEqual(json.loads(cache_file.read_text())["schema"], 1)

    def test_empty_or_invalid_refresh_does_not_replace_cache(self):
        original = parse_locations(sample_output())
        self.assertTrue(save_location_cache(original, "old"))
        self.assertFalse(save_location_cache([], "new"))
        self.assertFalse(save_location_cache([{"city": "broken"}], "new"))
        loaded, updated_at = load_location_cache()
        self.assertEqual(loaded, original)
        self.assertEqual(updated_at, "old")

    def test_refresh_interval_defaults_and_persists(self):
        self.assertEqual(load_refresh_interval(), 30)
        self.assertTrue(save_refresh_interval(60))
        self.assertEqual(load_refresh_interval(), 60)
        self.assertFalse(save_refresh_interval(15))
        self.assertEqual(load_refresh_interval(), 60)


if __name__ == "__main__":
    unittest.main()
