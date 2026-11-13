"""Headless tests for per-application TUN routing policy generation."""
import unittest
import subprocess

from services.app_routing import (
    APP_SLICE, DIRECT_MARK, FWMARK, NFT_TABLE, ROUTE_TABLE,
    cgroup_level_for_component, cgroup_level_for_slice,
    nft_ruleset, route_script, scope_command, user_manager_component,
    RoutingError,
)


class AppRoutingPlannerTests(unittest.TestCase):
    PATH = "/user.slice/user-1000.slice/user@1000.service/app.slice"

    def test_user_manager_and_future_app_slice_levels(self):
        self.assertEqual(cgroup_level_for_component(self.PATH, "user@1000.service"), 3)
        self.assertEqual(cgroup_level_for_slice(self.PATH), 4)

    def test_existing_app_slice_level_is_detected(self):
        path = self.PATH + "/adguard-vpn-apps.slice/adguard-vpn-app-test.scope"
        self.assertEqual(cgroup_level_for_slice(path), 5)

    def test_cgroup_level_requires_user_manager_hierarchy(self):
        with self.assertRaises(RoutingError):
            cgroup_level_for_slice("/system.slice/example.service")

    def test_selected_only_policy_marks_only_managed_app_slice(self):
        rules = nft_ruleset("selected", 4, 3)
        self.assertIn(f"table inet {NFT_TABLE}", rules)
        self.assertIn(f'socket cgroupv2 level 4 "{APP_SLICE}" meta mark set {FWMARK}', rules)
        self.assertNotIn(user_manager_component(), rules)
        self.assertNotIn("flush ruleset", rules)

    def test_all_except_policy_marks_user_session_then_overrides_app_slice(self):
        rules = nft_ruleset("all_except_selected", 4, 3)
        self.assertIn('socket cgroupv2 level 3 "user@1000.service" meta mark set 0xAD61', rules)
        self.assertIn(f'socket cgroupv2 level 4 "{APP_SLICE}" meta mark set {DIRECT_MARK}', rules)

    def test_route_script_isolated_and_has_explicit_cleanup(self):
        script = route_script("selected", 4, 3)
        self.assertIn(f'table "{ROUTE_TABLE}"', script)
        self.assertIn("ip -6 route replace default", script)
        self.assertIn("nft -f -", script)
        self.assertIn("--cleanup", script)
        self.assertIn(f"fwmark {FWMARK}", script)
        self.assertNotIn("ip route flush main", script)
        self.assertNotIn("flush ruleset", script)

    def test_generated_route_script_passes_posix_shell_syntax_check(self):
        for mode in ("selected", "all_except_selected"):
            result = subprocess.run(
                ["sh", "-n"], input=route_script(mode, 4, 3),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_except_route_script_has_direct_policy_rule(self):
        script = route_script("all_except_selected", 4, 3)
        self.assertIn(f"fwmark {DIRECT_MARK} lookup main", script)
        self.assertIn('meta mark set 0xAD62', script)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            route_script("all", 4, 3)

    def test_scope_command_uses_user_slice_and_preserves_arguments(self):
        command = scope_command(["/usr/bin/example", "--url", "https://example.test"], "org.example.App")
        self.assertEqual(command[:3], ["systemd-run", "--user", "--scope"])
        self.assertIn(f"--slice={APP_SLICE}", command)
        self.assertEqual(command[-2:], ["--url", "https://example.test"])
        self.assertTrue(command[4].endswith(".scope"))


if __name__ == "__main__":
    unittest.main()
