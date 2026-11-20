"""Safety regression tests for the DNS manager.

These tests deliberately exercise only read-only/precondition paths. They do
not require NetworkManager, a live VPN connection, or elevated privileges.
"""
import tempfile
import unittest
from pathlib import Path

from services.dns_manager import DNSManager, DNSManagerError, TEST_PROFILES


class FakeRunner:
    def __init__(self, *, vpn_output="", vpn_code=0, active_output="", active_code=0):
        self.vpn_output = vpn_output
        self.vpn_code = vpn_code
        self.active_output = active_output
        self.active_code = active_code
        self.commands = []
        self.profile_output = ""
        self.device_output = ""

    def __call__(self, command, timeout=15):
        self.commands.append(list(command))
        if command[:2] == ["adguardvpn-cli", "status"]:
            return self.vpn_code, self.vpn_output
        if command[:2] == ["nmcli", "--colors"] and "device" in command:
            return 0, self.device_output
        if command[:2] == ["nmcli", "--colors"] and "connection" in command:
            if "show" in command and "--active" in command:
                return self.active_code, self.active_output
            if "show" in command and "id" not in command:
                return 0, self.profile_output
        return 0, ""


class DNSManagerSafetyTests(unittest.TestCase):
    def manager(self, runner):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return DNSManager(state_dir=Path(temp.name) / "state", runner=runner)

    def test_only_explicit_test_profiles_are_allowed(self):
        with self.assertRaises(ValueError):
            DNSManager(profiles=("Wired connection 1",))
        with self.assertRaises(ValueError):
            DNSManager(profiles=("DOD",))
        with self.assertRaises(ValueError):
            DNSManager(profiles=())

    def test_vpn_requires_connected_tun_status(self):
        runner = FakeRunner(vpn_output="Connected to Riga\nVPN is running on tun0")
        manager = self.manager(runner)
        connected, _ = manager.vpn_status()
        self.assertTrue(connected)

        runner.vpn_output = "Connected to Riga\nVPN is running on tun1"
        connected, _ = manager.vpn_status()
        self.assertTrue(connected)

        runner.vpn_output = "Connected to Riga\nVPN is running on tun7"
        connected, _ = manager.vpn_status()
        self.assertTrue(connected)

        runner.vpn_output = "Connected to RIGA in TUN mode, running on tun0"
        connected, _ = manager.vpn_status()
        self.assertTrue(connected)

        runner.vpn_output = "Connected to RIGA in TUN mode, running on tun7"
        connected, _ = manager.vpn_status()
        self.assertTrue(connected)

        runner.vpn_output = "Connected to Riga without TUN"
        connected, _ = manager.vpn_status()
        self.assertFalse(connected)

        runner.vpn_output = "Disconnected"
        connected, _ = manager.vpn_status()
        self.assertFalse(connected)

    def test_apply_refuses_when_vpn_is_not_confirmed_without_writing(self):
        runner = FakeRunner(vpn_output="Disconnected")
        manager = self.manager(runner)
        with self.assertRaisesRegex(DNSManagerError, "VPN is not confirmed"):
            manager.apply_adguard_dns()
        self.assertFalse(any(
            command[:3] == ["nmcli", "connection", "modify"]
            for command in runner.commands
        ))

    def test_apply_refuses_active_test_profile_without_writing(self):
        runner = FakeRunner(
            vpn_output="Connected to Riga\nVPN is running on tun0",
            active_output=f"{TEST_PROFILES[0]}:eth0",
        )
        manager = self.manager(runner)
        with self.assertRaisesRegex(DNSManagerError, "must be inactive"):
            manager.apply_adguard_dns()
        self.assertFalse(any(
            command[:3] == ["nmcli", "connection", "modify"]
            for command in runner.commands
        ))

    def test_dry_run_is_explicitly_read_only(self):
        runner = FakeRunner(
            vpn_output="Connected to Riga\nVPN is running on tun0",
            active_output=f"{TEST_PROFILES[0]}:eth0",
        )
        manager = self.manager(runner)
        result = manager.dry_run()
        self.assertFalse(result["changes_made"])
        self.assertEqual(
            result["profiles"][TEST_PROFILES[0]]["planned_dns"],
            ["46.243.231.30", "46.243.231.31"],
        )
        self.assertFalse(any(
            command[:3] == ["nmcli", "connection", "modify"]
            for command in runner.commands
        ))

    def test_discovery_lists_real_wired_and_wifi_profiles_without_writing(self):
        runner = FakeRunner()
        runner.profile_output = (
            "Home\\: office:uuid-1:802-3-ethernet:enp3s0\n"
            "Guest Wi-Fi:uuid-2:802-11-wireless:wlp2s0\n"
            "VPN:uuid-3: tun: tun0"
        )
        runner.active_output = "Home\\: office:enp3s0"
        runner.device_output = (
            "enp3s0:ethernet:connected:Home\\: office\n"
            "wlp2s0:wifi:disconnected:--\n"
            "lo:loopback:connected:lo"
        )
        manager = self.manager(runner)

        profiles = manager.discover_profiles()
        interfaces = manager.network_interfaces()

        self.assertEqual([item["name"] for item in profiles],
                         ["Home: office", "Guest Wi-Fi"])
        self.assertTrue(profiles[0]["active"])
        self.assertFalse(profiles[1]["active"])
        self.assertEqual([item["device"] for item in interfaces],
                         ["enp3s0", "wlp2s0"])
        self.assertFalse(any(
            command[:3] == ["nmcli", "connection", "modify"]
            for command in runner.commands
        ))


if __name__ == "__main__":
    unittest.main()
