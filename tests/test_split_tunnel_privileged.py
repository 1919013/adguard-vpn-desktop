"""Tests for the narrow privileged split-tunnel helper."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.split_tunnel_privileged import (
    HelperError, SplitTunnelPrivilegedHelper, _validate,
)


class FakeRunner:
    def __init__(self, fail_ip_add=False):
        self.calls = []
        self.fail_ip_add = fail_ip_add

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("input")))
        if argv[:3] == ["nft", "list", "tables"]:
            return SimpleNamespace(returncode=0, stdout="")
        if argv[:3] == ["nft", "list", "table"]:
            return SimpleNamespace(returncode=0, stdout='table inet adguard_vpn_desktop { comment "Owned by ADGuard VPN Desktop"; }')
        if argv[:3] == ["ip", "-j", "rule"]:
            return SimpleNamespace(returncode=0, stdout='[{"priority":0,"table":"local"}]')
        if argv[:3] == ["ip", "rule", "add"] and self.fail_ip_add:
            return SimpleNamespace(returncode=2, stdout="simulated failure")
        return SimpleNamespace(returncode=0, stdout="")


class PrivilegedHelperTests(unittest.TestCase):
    def test_rejects_unsafe_scope_and_values(self):
        with self.assertRaises(HelperError):
            _validate("../../evil.scope", 5, 880, 0xAD61, 1061)
        with self.assertRaises(HelperError):
            _validate("good.scope", 0, 880, 0xAD61, 1061)

    def test_apply_creates_only_fixed_nft_and_ip_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            helper = SplitTunnelPrivilegedHelper(Path(tmp) / "state.json", runner, lambda: 0, lambda name: "/usr/sbin/nft")
            result = helper.apply(scope="adguard-vpn-firefox.scope", level=5, table=880)
            self.assertTrue(result["active"])
            state = json.loads((Path(tmp) / "state.json").read_text())
            self.assertEqual(state["phase"], "active")
            nft_call = next(call for call in runner.calls if call[0][:2] == ["nft", "-f"])
            self.assertIn("socket cgroupv2 level 5 adguard-vpn-firefox.scope", nft_call[1])
            self.assertTrue(any(call[0][:3] == ["ip", "rule", "add"] for call in runner.calls))

    def test_rolls_back_nft_if_ip_rule_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(fail_ip_add=True)
            helper = SplitTunnelPrivilegedHelper(Path(tmp) / "state.json", runner, lambda: 0, lambda name: "/usr/sbin/nft")
            with self.assertRaises(HelperError):
                helper.apply(scope="adguard-vpn-firefox.scope", level=5, table=880)
            self.assertFalse((Path(tmp) / "state.json").exists())
            self.assertTrue(any(call[0][:3] == ["nft", "delete", "table"] for call in runner.calls))

    def test_refuses_non_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = SplitTunnelPrivilegedHelper(Path(tmp) / "state.json", FakeRunner(), lambda: 1000)
            with self.assertRaises(HelperError):
                helper.apply(scope="test.scope", level=5, table=880)

    def test_remove_reconstructs_commands_from_owned_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({
                "owner": "adguard-vpn-desktop", "scope": "test.scope",
                "level": 5, "table": 880, "mark": 0xAD61,
                "priority": 1061, "phase": "active",
            }))
            runner = FakeRunner()
            helper = SplitTunnelPrivilegedHelper(state_path, runner, lambda: 0, lambda name: "/usr/sbin/nft")
            result = helper.remove()
            self.assertTrue(result["removed"])
            self.assertFalse(state_path.exists())
            self.assertTrue(any(call[0][:3] == ["ip", "rule", "del"] for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ["nft", "delete", "table"] for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
