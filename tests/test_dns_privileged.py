"""Unit tests for temporary, profile-preserving NetworkManager DNS changes."""
import os
import tempfile
import unittest
from pathlib import Path

from services.dns_privileged import TemporaryDNSHelper, DNSHelperError


UUID_ETH = "11111111-1111-4111-8111-111111111111"
UUID_WIFI = "22222222-2222-4222-8222-222222222222"


class FakeNetwork:
    def __init__(self):
        self.modified = set()
        self.uuids = {"enp1s0": UUID_ETH, "wlp2s0": UUID_WIFI}
        self.commands = []

    def __call__(self, argv, *, timeout=12):
        self.commands.append(list(argv))
        if argv[:2] == ["adguardvpn-cli", "status"]:
            return 0, "Connected to Tallinn\nrunning on tun0"
        if argv[:2] == ["ip", "-j"]:
            return 0, '[{"dev":"tun0"}]'
        if argv[:2] == ["nmcli", "--colors"] and "device" in argv and "show" in argv:
            if argv[-1] in self.uuids and "--fields" in argv:
                iface = argv[-1]
                return 0, (
                    f"GENERAL.DEVICE:{iface}\n"
                    f"GENERAL.CON-UUID:{self.uuids[iface]}\n"
                )
            return 0, (
                f"GENERAL.DEVICE:enp1s0\nGENERAL.TYPE:ethernet\n"
                f"GENERAL.STATE:100 (connected)\nGENERAL.CON-UUID:{UUID_ETH}\n"
                f"GENERAL.DEVICE:wlp2s0\nGENERAL.TYPE:wifi\n"
                f"GENERAL.STATE:100 (connected)\nGENERAL.CON-UUID:{UUID_WIFI}\n"
                f"GENERAL.DEVICE:tun0\nGENERAL.TYPE:tun\n"
                f"GENERAL.STATE:100 (connected)\nGENERAL.CON-UUID:--\n"
            )
        if argv[:3] == ["nmcli", "device", "modify"]:
            self.modified.add(argv[3])
            return 0, "success"
        if argv[:3] == ["nmcli", "device", "reapply"]:
            self.modified.discard(argv[3])
            return 0, "success"
        if argv[:2] == ["nmcli", "--colors"] and "IP4.DNS,IP6.DNS" in argv:
            iface = argv[-1]
            if iface in self.modified:
                return 0, (
                    "IP4.DNS:46.243.231.30\n"
                    "IP4.DNS:46.243.231.31\n"
                )
            return 0, "IP4.DNS:192.0.2.53\n"
        if argv[:2] == ["systemctl", "start"]:
            return 0, ""
        if argv[:2] == ["systemctl", "is-active"]:
            return 0, "active"
        if argv[:2] == ["systemctl", "stop"]:
            return 0, ""
        return 0, ""


class TemporaryDNSHelperTests(unittest.TestCase):
    def make_helper(self, root, runner):
        return TemporaryDNSHelper(
            state_file=Path(root) / "dns-runtime.json",
            runner=runner,
            euid=lambda: 0,
            uid=os.getuid,
            manage_guard=False,
        )

    def test_apply_changes_runtime_devices_and_restore_reapplies_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeNetwork()
            helper = self.make_helper(tmp, fake)
            result = helper.apply("tun0")
            self.assertTrue(result["active"])
            self.assertEqual(set(fake.modified), {"enp1s0", "wlp2s0"})
            self.assertTrue(Path(tmp, "dns-runtime.json").exists())
            self.assertFalse(any(
                command[:2] == ["nmcli", "connection"] and "modify" in command
                for command in fake.commands
            ))
            restored = helper.restore()
            self.assertTrue(restored["restored"])
            self.assertFalse(fake.modified)
            self.assertFalse(Path(tmp, "dns-runtime.json").exists())
            self.assertEqual(
                sum(command[:3] == ["nmcli", "device", "reapply"] for command in fake.commands),
                2,
            )

    def test_refuses_when_dns_route_does_not_use_tunnel(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeNetwork()
            def runner(argv, *, timeout=12):
                if argv[:2] == ["ip", "-j"]:
                    return 0, '[{"dev":"enp1s0"}]'
                return fake(argv, timeout=timeout)
            helper = self.make_helper(tmp, runner)
            with self.assertRaises(DNSHelperError):
                helper.apply("tun0")
            self.assertFalse(fake.modified)

    def test_restore_does_not_touch_a_replaced_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeNetwork()
            helper = self.make_helper(tmp, fake)
            helper.apply("tun0")
            fake.uuids["enp1s0"] = "33333333-3333-4333-8333-333333333333"
            restored = helper.restore()
            results = {item["ifname"]: item["result"] for item in restored["devices"]}
            self.assertEqual(results["enp1s0"], "skipped-connection-changed")
            self.assertEqual(results["wlp2s0"], "restored-from-active-profile")
            self.assertIn("enp1s0", fake.modified)

    def test_refuses_when_vpn_is_disconnected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeNetwork()
            def runner(argv, *, timeout=12):
                if argv[:2] == ["adguardvpn-cli", "status"]:
                    return 0, "Disconnected"
                return fake(argv, timeout=timeout)
            helper = self.make_helper(tmp, runner)
            with self.assertRaises(DNSHelperError):
                helper.apply("tun0")
            self.assertFalse(fake.modified)


if __name__ == "__main__":
    unittest.main()
