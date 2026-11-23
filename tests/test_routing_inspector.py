"""Tests for live routing inspection."""
import json
import unittest

from services.routing_inspector import RoutingInspector


class RoutingInspectorTests(unittest.TestCase):
    def test_discovers_vpn_table_without_hardcoding_table_number(self):
        data = {
            "status": (0, "Connected to Riga in TUN mode, running on tun0"),
            "v4": (0, json.dumps([{"dst": "default", "dev": "tun0", "table": 880}])),
            "v6": (0, json.dumps([{"dst": "::/0", "dev": "tun0", "table": 880}])),
            "rules": (0, '[{"priority": 0, "table": "local"}]'),
        }

        def runner(command, timeout=8):
            if command[:2] == ["adguardvpn-cli", "status"]:
                return data["status"]
            if command[:3] == ["ip", "-j", "-4"]:
                return data["v4"]
            if command[:3] == ["ip", "-j", "-6"]:
                return data["v6"]
            if command[:3] == ["ip", "-j", "rule"]:
                return data["rules"]
            if command[:3] == ["ip", "-j", "-details"]:
                return 0, "[]"
            return 1, "unexpected command"

        snapshot = RoutingInspector(runner=runner).inspect()
        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.tunnel_interface, "tun0")
        self.assertEqual(snapshot.vpn_tables, ("880",))

    def test_warns_when_tun_route_table_is_missing(self):
        def runner(command, timeout=8):
            if command[:2] == ["adguardvpn-cli", "status"]:
                return 0, "Connected in TUN mode, running on tun0"
            if command[:3] == ["ip", "-j", "-details"]:
                return 0, "[]"
            if command[:3] == ["ip", "-j", "-4"]:
                return 0, "[]"
            if command[:3] == ["ip", "-j", "-6"]:
                return 0, "[]"
            if command[:3] == ["ip", "-j", "rule"]:
                return 0, "[]"
            return 1, "unexpected"

        snapshot = RoutingInspector(runner=runner).inspect()
        self.assertEqual(snapshot.vpn_tables, ())
        self.assertTrue(any("Не найдена таблица" in warning for warning in snapshot.warnings))


if __name__ == "__main__":
    unittest.main()
