import unittest
from unittest.mock import patch

from core.vpn import VPNService


CLI_OUTPUT = (
    "ISO   COUNTRY              CITY                           PING ESTIMATE\n"
    "EE    Estonia              Tallinn                        65\n"
)


class VPNLocationFallbackTests(unittest.TestCase):
    def test_list_locations_uses_last_good_cache_after_cli_error(self):
        cached = [{"iso": "EE", "country": "Estonia", "city": "Tallinn",
                   "ping": 65, "label": "Tallinn, Estonia — 65 мс"}]
        runner = lambda args, timeout: (124, "Command timed out")
        with patch("core.vpn.load_location_cache",
                   return_value=(cached, "2026-11-26T17:00:00+00:00")):
            code, output, locations, from_cache, updated_at = VPNService(runner).list_locations()
        self.assertEqual(code, 124)
        self.assertIn("timed out", output.lower())
        self.assertEqual(locations, cached)
        self.assertTrue(from_cache)
        self.assertTrue(updated_at.startswith("2026-11-26"))

    def test_list_locations_saves_only_successful_nonempty_result(self):
        calls = []
        def runner(args, timeout):
            calls.append((args, timeout))
            return 0, CLI_OUTPUT

        with patch("core.vpn.load_location_cache", return_value=([], None)), \
             patch("core.vpn.save_location_cache", return_value=True) as save:
            code, output, locations, from_cache, updated_at = VPNService(runner).list_locations()

        self.assertEqual(calls, [(["list-locations"], 12)])
        self.assertEqual(code, 0)
        self.assertEqual(locations[0]["city"], "Tallinn")
        self.assertFalse(from_cache)
        self.assertTrue(updated_at)
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
