from unittest.mock import patch

from core.vpn import VPNService


CLI_OUTPUT = (
    "ISO   COUNTRY              CITY                           PING ESTIMATE\n"
    "EE    Estonia              Tallinn                        65\n"
)


def test_list_locations_uses_last_good_cache_after_cli_error():
    cached = [{"iso": "EE", "country": "Estonia", "city": "Tallinn",
               "ping": 65, "label": "Tallinn, Estonia — 65 мс"}]
    runner = lambda args, timeout: (124, "Command timed out")
    with patch("core.vpn.load_location_cache", return_value=(cached, "2026-11-26T17:00:00+00:00")):
        code, output, locations, from_cache, updated_at = VPNService(runner).list_locations()
    assert code == 124
    assert "timed out" in output.lower()
    assert locations == cached
    assert from_cache is True
    assert updated_at.startswith("2026-11-26")


def test_list_locations_saves_only_successful_nonempty_result():
    calls = []
    def runner(args, timeout):
        calls.append((args, timeout))
        return 0, CLI_OUTPUT

    with patch("core.vpn.load_location_cache", return_value=([], None)), \
         patch("core.vpn.save_location_cache", return_value=True) as save:
        code, output, locations, from_cache, updated_at = VPNService(runner).list_locations()

    assert calls == [(["list-locations"], 12)]
    assert code == 0
    assert locations[0]["city"] == "Tallinn"
    assert from_cache is False
    assert updated_at
    save.assert_called_once()
