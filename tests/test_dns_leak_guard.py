"""Tests for the read-only DNS leak guard."""
import tempfile
import unittest
from pathlib import Path

from services.dns_leak_guard import DNSLeakGuard


class DNSLeakGuardTests(unittest.TestCase):
    def test_ready_only_when_cli_and_system_dns_match_and_route_over_tun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / "cli-resolv.conf"
            active = root / "resolv.conf"
            cli.write_text("nameserver 46.243.231.30\nnameserver 46.243.231.31\n")
            active.write_text("nameserver 46.243.231.30\nnameserver 46.243.231.31\n")

            def runner(argv, timeout=8):
                return 0, '[{"dst":"46.243.231.30","dev":"tun0"}]' if argv[-1] == "46.243.231.30" else '[{"dst":"46.243.231.31","dev":"tun0"}]'

            guard = DNSLeakGuard(runner=runner, resolv_conf=active, cli_resolv_conf=cli, query_probe=lambda _server: (True, "test DNS reply"))
            result = guard.inspect("tun0")
            self.assertTrue(result["ready"], result["reasons"])
            self.assertEqual(set(result["servers"]), {"46.243.231.30", "46.243.231.31"})

    def test_refuses_mismatched_system_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / "cli-resolv.conf"
            active = root / "resolv.conf"
            cli.write_text("nameserver 46.243.231.30\n")
            active.write_text("nameserver 192.168.17.3\n")
            guard = DNSLeakGuard(
                runner=lambda argv, timeout=8: (0, '[{"dev":"tun0"}]'),
                resolv_conf=active, cli_resolv_conf=cli,
                query_probe=lambda _server: (True, "test DNS reply"),
            )
            result = guard.inspect("tun0")
            self.assertFalse(result["ready"])
            self.assertTrue(any("не совпадают" in reason for reason in result["reasons"]))

    def test_refuses_dns_route_outside_tunnel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / "cli-resolv.conf"
            active = root / "resolv.conf"
            cli.write_text("nameserver 46.243.231.30\n")
            active.write_text("nameserver 46.243.231.30\n")
            guard = DNSLeakGuard(
                runner=lambda argv, timeout=8: (0, '[{"dev":"enp1s0"}]'),
                resolv_conf=active, cli_resolv_conf=cli,
            )
            result = guard.inspect("tun0")
            self.assertFalse(result["ready"])
            self.assertTrue(any("не подтверждён через tun0" in reason for reason in result["reasons"]))

    def test_refuses_loopback_stub_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / "cli-resolv.conf"
            active = root / "resolv.conf"
            cli.write_text("nameserver 46.243.231.30\n")
            active.write_text("nameserver 127.0.0.53\n")
            guard = DNSLeakGuard(resolv_conf=active, cli_resolv_conf=cli)
            result = guard.inspect("tun0")
            self.assertFalse(result["ready"])
            self.assertTrue(any("DNS-stub" in reason for reason in result["reasons"]))

    def test_refuses_unreachable_dns_upstream_even_when_route_is_tun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / "cli-resolv.conf"
            active = root / "resolv.conf"
            cli.write_text("nameserver 46.243.231.30\n")
            active.write_text("nameserver 46.243.231.30\\n")
            guard = DNSLeakGuard(
                runner=lambda argv, timeout=8: (0, '[{"dev":"tun0"}]'),
                resolv_conf=active,
                cli_resolv_conf=cli,
                query_probe=lambda _server: (False, "timeout"),
            )
            result = guard.inspect("tun0")
            self.assertFalse(result["ready"])
            self.assertTrue(any("реального DNS-запроса" in reason for reason in result["reasons"]))


if __name__ == "__main__":
    unittest.main()
