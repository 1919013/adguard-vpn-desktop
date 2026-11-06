"""Tests for dynamic NetworkManager discovery."""
import unittest

from services.network_manager import NetworkManagerService, _split_terse


class NetworkManagerTests(unittest.TestCase):
    def test_split_terse_preserves_escaped_colons(self):
        self.assertEqual(_split_terse(r"Office\: guest:uuid:type:eth0"),
                         ["Office: guest", "uuid", "type", "eth0"])

    def test_devices_are_discovered_without_hardcoded_names(self):
        def runner(args):
            if args == ["device", "status"]:
                return 0, (
                    "DEVICE:TYPE:STATE:CONNECTION\n"
                    "enp2s0:ethernet:connected:Office LAN\n"
                    "wlp3s0:wifi:disconnected:--\n"
                    "lo:loopback:connected:lo\n"
                )
            raise AssertionError(args)

        self.assertEqual(
            NetworkManagerService(runner).devices(),
            [
                {"name": "enp2s0", "type": "ethernet", "state": "connected",
                 "connection": "Office LAN"},
                {"name": "wlp3s0", "type": "wifi", "state": "disconnected",
                 "connection": ""},
            ],
        )

    def test_profiles_are_discovered_dynamically(self):
        def runner(args):
            self.assertEqual(args, ["connection", "show"])
            return 0, (
                "NAME:UUID:TYPE:DEVICE\n"
                "Home Wi-Fi:abc-123:802-11-wireless:wlp3s0\n"
                "Wired profile:def-456:802-3-ethernet:--\n"
            )

        self.assertEqual(
            NetworkManagerService(runner).profiles(),
            [
                {"name": "Home Wi-Fi", "uuid": "abc-123",
                 "type": "802-11-wireless", "device": "wlp3s0"},
                {"name": "Wired profile", "uuid": "def-456",
                 "type": "802-3-ethernet", "device": ""},
            ],
        )

    def test_discovery_errors_are_reported(self):
        service = NetworkManagerService(lambda _args: (1, "NetworkManager unavailable"))
        with self.assertRaisesRegex(RuntimeError, "NetworkManager unavailable"):
            service.devices()


if __name__ == "__main__":
    unittest.main()
