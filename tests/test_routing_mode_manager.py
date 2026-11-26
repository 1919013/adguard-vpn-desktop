"""Tests for AdGuard VPN CLI routing mode changes."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from services.routing_mode_manager import (
    parse_cli_routing_config, read_cli_routing_config,
    set_cli_routing_mode, RoutingModeError,
)


CONFIG = """VPN mode: TUN
Tunnel routing mode: AUTO
Change system DNS: on
"""


class FakeCLI:
    def __init__(self, mode="AUTO", dns=True):
        self.mode = mode
        self.dns = dns
        self.commands = []

    def __call__(self, args, timeout=12):
        self.commands.append(list(args))
        if args == ["config", "show"]:
            return 0, (
                "VPN mode: TUN\n"
                f"Tunnel routing mode: {self.mode}\n"
                f"Change system DNS: {'on' if self.dns else 'off'}\n"
            )
        if args[:2] == ["config", "set-change-system-dns"]:
            self.dns = args[2] == "on"
            return 0, "ok"
        if args[:2] == ["config", "set-tun-routing-mode"]:
            self.mode = args[2]
            return 0, "ok"
        return 1, "unsupported"


class RoutingModeManagerTests(unittest.TestCase):
    def test_parser_reads_tun_auto_and_dns(self):
        parsed = parse_cli_routing_config(CONFIG)
        self.assertEqual(parsed["vpn_mode"], "TUN")
        self.assertEqual(parsed["routing_mode"], "AUTO")
        self.assertTrue(parsed["change_system_dns"])
        self.assertTrue(parsed["dns_setting_known"])

    def test_switches_all_apps_to_auto(self):
        cli = FakeCLI(mode="SCRIPT")
        result = set_cli_routing_mode("AUTO", cli)
        self.assertEqual(result["routing_mode"], "AUTO")
        self.assertEqual(cli.mode, "AUTO")
        self.assertIn(["config", "set-tun-routing-mode", "AUTO"], cli.commands)

    def test_switches_selected_apps_to_script_when_route_script_exists(self):
        cli = FakeCLI(mode="AUTO")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "setup_routes.sh"
            script.write_text("#!/bin/sh\\n", encoding="utf-8")
            script.chmod(0o700)
            with patch("services.routing_mode_manager.route_script_path", return_value=script):
                result = set_cli_routing_mode("SCRIPT", cli)
        self.assertEqual(result["routing_mode"], "SCRIPT")
        self.assertEqual(cli.mode, "SCRIPT")
        self.assertIn(["config", "set-tun-routing-mode", "SCRIPT"], cli.commands)
        self.assertNotIn(["config", "create-route-script"], cli.commands)

    def test_refuses_script_mode_without_executable_route_script(self):
        cli = FakeCLI(mode="AUTO")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "missing.sh"
            with patch("services.routing_mode_manager.route_script_path", return_value=script):
                with self.assertRaises(RoutingModeError):
                    set_cli_routing_mode("SCRIPT", cli)
        self.assertEqual(cli.mode, "AUTO")
        self.assertNotIn(["config", "set-tun-routing-mode", "SCRIPT"], cli.commands)

    def test_enables_system_dns_before_changing_mode(self):
        cli = FakeCLI(mode="SCRIPT", dns=False)
        result = set_cli_routing_mode("AUTO", cli)
        self.assertTrue(result["change_system_dns"])
        self.assertTrue(cli.dns)
        self.assertLess(
            cli.commands.index(["config", "set-change-system-dns", "on"]),
            cli.commands.index(["config", "set-tun-routing-mode", "AUTO"]),
        )

    def test_refuses_socks_without_changing_configuration(self):
        def runner(args, timeout=12):
            return 0, "VPN mode: SOCKS\nTunnel routing mode: AUTO\nChange system DNS: off\n"
        with self.assertRaises(RoutingModeError):
            set_cli_routing_mode("SCRIPT", runner)

    def test_unknown_cli_output_fails_closed(self):
        with self.assertRaises(RoutingModeError):
            read_cli_routing_config(lambda args, timeout=12: (0, "unrecognized output"))


if __name__ == "__main__":
    unittest.main()
