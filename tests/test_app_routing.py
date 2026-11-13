"""Tests for the unprivileged per-application routing planner."""
import unittest
from services.app_routing import (
    APP_SLICE, FWMARK, NFT_TABLE, ROUTE_TABLE,
    build_plan, cgroup_level_for_slice, nft_ruleset, route_script, scope_command, RoutingError,
)


class AppRoutingPlannerTests(unittest.TestCase):
    def test_cgroup_level_tracks_systemd_user_hierarchy(self):
        path = "/user.slice/user-1000.slice/user@1000.service/app.slice"
        self.assertEqual(cgroup_level_for_slice(path), 4)

    def test_cgroup_level_does_not_duplicate_slice(self):
        path = "/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-apps.slice"
        self.assertEqual(cgroup_level_for_slice(path), 5)

    def test_cgroup_level_requires_user_manager_hierarchy(self):
        with self.assertRaises(RoutingError):
            cgroup_level_for_slice("/system.slice/example.service")

    def test_nft_rules_are_confined_to_owned_table(self):
        rules = nft_ruleset(5)
        self.assertIn(f"table inet {NFT_TABLE}", rules)
        self.assertIn('socket cgroupv2 level 5 "adguard-vpn-apps.slice"', rules)
        self.assertIn(f"meta mark set {FWMARK}", rules)
        self.assertNotIn("flush ruleset", rules)

    def test_route_script_uses_dedicated_table_and_both_families(self):
        script = route_script()
        self.assertIn(f"table {ROUTE_TABLE}", script)
        self.assertIn("ip -6 route replace", script)
        self.assertIn("nft -f -", script)
        self.assertIn("socket cgroupv2 level 5", script)
        self.assertIn(f"fwmark {FWMARK}", script)
        self.assertNotIn("ip route flush", script)

    def test_build_plan_is_pure_and_validates_interface(self):
        plan = build_plan("tun0", "/user.slice/user-1000.slice/user@1000.service/app.slice")
        self.assertEqual(plan["interface"], "tun0")
        self.assertEqual(plan["scope_slice"], APP_SLICE)
        with self.assertRaises(ValueError):
            build_plan("tun0;reboot", "/user.slice")

    def test_scope_command_uses_systemd_user_slice_and_keeps_arguments(self):
        command = scope_command(["/usr/bin/example", "--url", "https://example.test"], "org.example.App")
        self.assertEqual(command[:3], ["systemd-run", "--user", "--scope"])
        self.assertIn(f"--slice={APP_SLICE}", command)
        self.assertEqual(command[-2:], ["--url", "https://example.test"])
        self.assertTrue(command[4].endswith(".scope"))


if __name__ == "__main__":
    unittest.main()
