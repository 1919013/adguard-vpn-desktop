"""Tests for read-only NetworkManager device discovery."""
import unittest

from services.network_manager import NetworkManagerInventory, NetworkManagerError


class NetworkManagerInventoryTests(unittest.TestCase):
    def test_discovers_active_physical_links_without_hardcoded_names(self):
        output = """GENERAL.DEVICE:enp1s0
GENERAL.TYPE:ethernet
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:Office wired
IP4.DNS:192.0.2.53
IP6.DNS:2001:db8::53
GENERAL.DEVICE:wlp2s0
GENERAL.TYPE:wifi
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:Home Wi-Fi
IP4.DNS:192.0.2.54
GENERAL.DEVICE:tun0
GENERAL.TYPE:tun
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:VPN
IP4.DNS:46.243.231.30
GENERAL.DEVICE:lo
GENERAL.TYPE:loopback
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:lo
"""
        manager = NetworkManagerInventory(runner=lambda _argv: (0, output))
        devices = manager.active_physical_devices()
        self.assertEqual([item["name"] for item in devices], ["enp1s0", "wlp2s0"])
        self.assertEqual(devices[0]["dns4"], ("192.0.2.53",))
        self.assertEqual(devices[0]["dns6"], ("2001:db8::53",))
        self.assertEqual(devices[1]["connection"], "Home Wi-Fi")

    def test_skips_disconnected_physical_devices(self):
        output = """GENERAL.DEVICE:enp2s0
GENERAL.TYPE:ethernet
GENERAL.STATE:30 (disconnected)
GENERAL.CONNECTION:--
"""
        manager = NetworkManagerInventory(runner=lambda _argv: (0, output))
        self.assertEqual(manager.devices(), [])

    def test_nmcli_failure_is_reported(self):
        manager = NetworkManagerInventory(runner=lambda _argv: (10, "NetworkManager unavailable"))
        with self.assertRaises(NetworkManagerError):
            manager.devices()


if __name__ == "__main__":
    unittest.main()
