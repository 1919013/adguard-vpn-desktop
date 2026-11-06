"""Tests for read-only IP and DNS diagnostics."""
import unittest

from services.network_diagnostics import NetworkDiagnostics


class NetworkDiagnosticsTests(unittest.TestCase):
    def test_collects_local_route_and_dns_information(self):
        expected = {
            "addresses": ["ip", "-brief", "address"],
            "ipv4_default_route": ["ip", "-4", "route", "show", "default"],
            "ipv6_default_route": ["ip", "-6", "route", "show", "default"],
            "dns_by_device": [
                "nmcli", "--colors", "no", "--fields",
                "GENERAL.DEVICE,IP4.DNS,IP6.DNS", "device", "show",
            ],
        }
        def runner(args):
            for key, command in expected.items():
                if args == command:
                    return 0, key
            raise AssertionError(args)

        result = NetworkDiagnostics(runner).collect()
        self.assertEqual(set(result), set(expected))
        self.assertEqual(result["ipv4_default_route"], (0, "ipv4_default_route"))
        self.assertEqual(result["dns_by_device"], (0, "dns_by_device"))

    def test_command_failures_are_preserved(self):
        diagnostics = NetworkDiagnostics(lambda _args: (1, "not available"))
        result = diagnostics.collect()
        self.assertEqual(result["addresses"], (1, "not available"))


if __name__ == "__main__":
    unittest.main()
