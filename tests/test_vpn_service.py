"""Tests for the documented AdGuard VPN CLI wrappers."""
import unittest

from core.vpn import VPNService


class VPNServiceTests(unittest.TestCase):
    def test_version_and_update_commands(self):
        calls = []
        def runner(args, timeout=25):
            calls.append((args, timeout))
            return 0, "ok"
        service = VPNService(runner)
        self.assertEqual(service.version(), (0, "ok"))
        self.assertEqual(service.check_update(), (0, "ok"))
        self.assertEqual(service.update(), (0, "ok"))
        self.assertEqual(calls[0][0], ["--version"])
        self.assertEqual(calls[1][0], ["check-update"])
        self.assertEqual(calls[2][0], ["update", "-y"])

    def test_bound_interface_is_validated_and_passed_as_one_argument(self):
        calls = []
        def runner(args, timeout=25):
            calls.append(args)
            return 0, "ok"
        service = VPNService(runner)
        self.assertEqual(service.set_bound_interface("wlp3s0"), (0, "ok"))
        self.assertEqual(calls[-1], ["config", "set-bound-if-override", "wlp3s0"])
        self.assertEqual(service.set_bound_interface("bad name")[0], 2)
        self.assertEqual(len(calls), 1)

    def test_clear_bound_interface(self):
        calls = []
        service = VPNService(lambda args, timeout=25: (calls.append(args) or 0, "ok"))
        self.assertEqual(service.clear_bound_interface(), (0, "ok"))
        self.assertEqual(calls, [["config", "set-bound-if-override", ""]])


if __name__ == "__main__":
    unittest.main()
