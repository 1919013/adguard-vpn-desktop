"""Headless tests for dynamic network-interface discovery."""
import json
import unittest
from unittest.mock import patch

from modules.interfaces import (
    NetworkInterface, _parse_nmcli_device_status, discover_interfaces,
)


class NetworkInterfaceTests(unittest.TestCase):
    def test_nmcli_parser_preserves_escaped_colons(self):
        parsed = _parse_nmcli_device_status(
            r"enp1s0:ethernet:connected:Office\: wired" + "\n"
            + r"wlp2s0:wifi:connected:Home\\Guest"
        )
        self.assertEqual(parsed["enp1s0"], ("ethernet", "connected", "Office: wired"))
        self.assertEqual(parsed["wlp2s0"], ("wifi", "connected", r"Home\Guest"))

    def test_discovery_uses_runtime_devices_and_excludes_tunnels(self):
        links = [
            {"ifname": "lo", "link_type": "loopback", "flags": ["UP"]},
            {"ifname": "enp7s0", "link_type": "ether", "flags": ["UP"]},
            {"ifname": "wlp4s0", "link_type": "ether", "flags": ["UP"]},
            {"ifname": "tun0", "link_type": "none", "linkinfo": {"info_kind": "tun"}},
            {"ifname": "wg-office", "link_type": "none", "linkinfo": {"info_kind": "wireguard"}},
        ]
        nmcli = (
            "enp7s0:ethernet:connected:Office\\: LAN\n"
            "wlp4s0:wifi:disconnected:--"
        )
        with patch("modules.interfaces._run", side_effect=[
            (0, json.dumps(links)), (0, nmcli)
        ]):
            found = discover_interfaces()
        self.assertEqual([item.name for item in found], ["enp7s0", "wlp4s0"])
        self.assertEqual(found[0], NetworkInterface(
            "enp7s0", "ethernet", "connected", "Office: LAN"
        ))
        self.assertEqual(found[1].connection, "--")

    def test_discovery_keeps_unmanaged_physical_device(self):
        links = [{"ifname": "enx123", "link_type": "ether", "flags": []}]
        with patch("modules.interfaces._run", side_effect=[
            (0, json.dumps(links)), (10, "NetworkManager unavailable")
        ]):
            found = discover_interfaces()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "enx123")
        self.assertEqual(found[0].state, "не управляется NetworkManager")

    def test_invalid_ip_json_is_reported(self):
        with patch("modules.interfaces._run", return_value=(0, "not-json")):
            with self.assertRaisesRegex(RuntimeError, "некорректный список"):
                discover_interfaces()


if __name__ == "__main__":
    unittest.main()
