"""Tests for read-only network interface discovery."""
import unittest

from services.interface_manager import InterfaceManager


class InterfaceManagerTests(unittest.TestCase):
    def test_discovers_interfaces_and_nm_state(self):
        def runner(command, timeout=8):
            if command[:3] == ["ip", "-j", "-details"]:
                return 0, '[{"ifname":"lo","flags":["LOOPBACK","UP"],"addr_info":[]},' \
                       '{"ifname":"enp2s0","flags":["BROADCAST","UP"],"link_type":"ether",' \
                       '"addr_info":[{"local":"192.0.2.5","prefixlen":24}]}]'
            if command[0] == "nmcli":
                return 0, "enp2s0:ethernet:подключено:Домашняя сеть"
            if command[:2] == ["adguardvpn-cli", "status"]:
                return 0, "Connected to RIGA in TUN mode, running on tun0"
            return 1, "unexpected"

        manager = InterfaceManager(runner=runner)
        items = manager.list_interfaces()
        self.assertEqual([item["name"] for item in items], ["enp2s0"])
        self.assertEqual(items[0]["addresses"], ["192.0.2.5/24"])
        self.assertIn("Домашняя сеть", items[0]["network_manager"])
        self.assertEqual(manager.adguard_path()["interface"], "tun0")

    def test_reports_disconnected_vpn(self):
        manager = InterfaceManager(
            runner=lambda command, timeout=8: (0, "Disconnected")
        )
        self.assertFalse(manager.adguard_path()["connected"])

    def test_rejects_invalid_ip_json(self):
        manager = InterfaceManager(
            runner=lambda command, timeout=8: (0, "not-json")
        )
        with self.assertRaises(Exception):
            manager.list_interfaces()


if __name__ == "__main__":
    unittest.main()
