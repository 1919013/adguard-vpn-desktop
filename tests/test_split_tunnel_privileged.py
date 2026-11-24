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
    def __init__(self, fail_ip_add=False, fail_ip_delete=False,
                 partial_ip_add=False, initial_rules=None):
        self.calls = []
        self.fail_ip_add = fail_ip_add
        self.fail_ip_delete = fail_ip_delete
        self.partial_ip_add = partial_ip_add
        self.rules = list(initial_rules or [{"priority": 0, "table": "local"}])
        self.nft_rules = ""

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("input")))
        if argv[:2] == ["nft", "-f"]:
            self.nft_rules = kwargs.get("input") or ""
            return SimpleNamespace(returncode=0, stdout="")
        if argv[:5] == ["nft", "list", "chain", "inet", "adguard_vpn_desktop"]:
            return SimpleNamespace(returncode=0, stdout=self.nft_rules)
        if argv[:3] == ["nft", "list", "tables"]:
            return SimpleNamespace(returncode=0, stdout="")
        if argv[:3] == ["nft", "list", "table"]:
            return SimpleNamespace(returncode=0, stdout='table inet adguard_vpn_desktop { comment "Owned by ADGuard VPN Desktop"; }')
        if argv[:4] == ["ip", "-j", "rule", "show"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.rules))
        if argv[:3] == ["ip", "rule", "add"] and self.fail_ip_add:
            if self.partial_ip_add:
                self.rules.append({"priority": int(argv[4]), "fwmark": argv[6], "table": argv[8]})
            return SimpleNamespace(returncode=2, stdout="simulated failure")
        if argv[:3] == ["ip", "rule", "add"]:
            self.rules.append({"priority": int(argv[4]), "fwmark": argv[6], "table": argv[8]})
            return SimpleNamespace(returncode=0, stdout="")
        if argv[:3] == ["ip", "rule", "del"] and self.fail_ip_delete:
            return SimpleNamespace(returncode=2, stdout="simulated delete failure")
        if argv[:3] == ["ip", "rule", "del"]:
            priority, mark, table = argv[4], argv[6], argv[8]
            self.rules = [
                rule for rule in self.rules
                if not (
                    str(rule.get("priority")) == priority
                    and str(rule.get("fwmark")) == mark
                    and str(rule.get("table")) == table
                )
            ]
            return SimpleNamespace(returncode=0, stdout="")
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
            result = helper.apply(scope="adguard-vpn-firefox.scope", level=5, table=880, cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope", tunnel_interface="tun0", dns_servers=["46.243.231.30"])
            self.assertTrue(result["active"])
            state = json.loads((Path(tmp) / "state.json").read_text())
            self.assertEqual(state["phase"], "active")
            nft_call = next(call for call in runner.calls if call[0][:2] == ["nft", "-f"])
            self.assertIn("socket cgroupv2 level 5 adguard-vpn-firefox.scope", nft_call[1])
            self.assertIn("ip daddr 46.243.231.30 udp dport 53 meta mark set 0xad61", nft_call[1])
            self.assertIn("ip daddr 46.243.231.30 tcp dport 53 meta mark set 0xad61", nft_call[1])
            self.assertIn('meta mark 0xad61 oifname != "tun0" drop', nft_call[1])
            self.assertIn('ip daddr 46.243.231.30 udp dport 53 oifname != "tun0" drop', nft_call[1])
            self.assertIn('ip daddr 46.243.231.30 tcp dport 53 oifname != "tun0" drop', nft_call[1])
            self.assertTrue(any(call[0][:3] == ["ip", "rule", "add"] for call in runner.calls))

    def test_rolls_back_nft_if_ip_rule_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(fail_ip_add=True)
            helper = SplitTunnelPrivilegedHelper(Path(tmp) / "state.json", runner, lambda: 0, lambda name: "/usr/sbin/nft")
            with self.assertRaises(HelperError):
                helper.apply(scope="adguard-vpn-firefox.scope", level=5, table=880, cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope", tunnel_interface="tun0", dns_servers=["46.243.231.30"])
            self.assertFalse((Path(tmp) / "state.json").exists())
            self.assertTrue(any(call[0][:3] == ["nft", "delete", "table"] for call in runner.calls))


    def test_partial_ip_add_failure_retains_recovery_state_if_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            runner = FakeRunner(
                fail_ip_add=True, fail_ip_delete=True, partial_ip_add=True,
            )
            helper = SplitTunnelPrivilegedHelper(
                state_path, runner, lambda: 0, lambda name: "/usr/sbin/nft"
            )
            with self.assertRaisesRegex(HelperError, "сохранено"):
                helper.apply(scope="adguard-vpn-firefox.scope", level=5, table=880, cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope", tunnel_interface="tun0", dns_servers=["46.243.231.30"])
            self.assertTrue(state_path.exists())
            state = json.loads(state_path.read_text())
            self.assertEqual(state["owner"], "adguard-vpn-desktop")
            self.assertTrue(any(
                rule.get("priority") == 1061 and rule.get("fwmark") == "0xad61"
                for rule in runner.rules
            ))
            self.assertFalse(any(
                call[0][:3] == ["nft", "delete", "table"] for call in runner.calls
            ))



    def test_verify_active_checks_exact_live_nft_and_ip_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            helper = SplitTunnelPrivilegedHelper(
                Path(tmp) / "state.json", runner, lambda: 0,
                lambda name: "/usr/sbin/nft"
            )
            helper.apply(scope="adguard-vpn-firefox.scope", level=5, table=880, cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope", tunnel_interface="tun0", dns_servers=["46.243.231.30"])
            self.assertTrue(helper.verify_active(
                scope="adguard-vpn-firefox.scope", level=5, table=880,
                cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope",
                tunnel_interface="tun0", dns_servers=["46.243.231.30"]
            ))
            self.assertFalse(helper.verify_active(
                scope="adguard-vpn-chrome.scope", level=5, table=880,
                cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-chrome.scope",
                tunnel_interface="tun0", dns_servers=["46.243.231.30"]
            ))

    def test_rejects_symlink_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.json"
            target.write_text(json.dumps({"owner": "adguard-vpn-desktop"}))
            link = root / "state.json"
            link.symlink_to(target)
            helper = SplitTunnelPrivilegedHelper(link, FakeRunner(), lambda: 0)
            with self.assertRaisesRegex(HelperError, "ссылкой"):
                helper._read_state()

    def test_rejects_world_accessible_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"owner": "adguard-vpn-desktop"}))
            state.chmod(0o644)
            helper = SplitTunnelPrivilegedHelper(state, FakeRunner(), lambda: 0)
            with self.assertRaisesRegex(HelperError, "Права файла"):
                helper._read_state()

    def test_refuses_insecure_state_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            root.mkdir(mode=0o777)
            root.chmod(0o755)
            helper = SplitTunnelPrivilegedHelper(root / "state.json", FakeRunner(), lambda: 0)
            with self.assertRaisesRegex(HelperError, "доступен посторонним"):
                helper._write_state({"owner": "adguard-vpn-desktop"})

    def test_refuses_non_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = SplitTunnelPrivilegedHelper(Path(tmp) / "state.json", FakeRunner(), lambda: 1000)
            with self.assertRaises(HelperError):
                helper.apply(scope="test.scope", level=5, table=880, cgroup_path="/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope", tunnel_interface="tun0", dns_servers=["46.243.231.30"])

    def test_remove_reconstructs_commands_from_owned_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({
                "owner": "adguard-vpn-desktop", "scope": "test.scope",
                "level": 5, "table": 880, "cgroup_path": "/user.slice/user-1000.slice/user@1000.service/app.slice/test.scope", "mark": 0xAD61,
                "priority": 1061, "phase": "active",
            }))
            state_path.chmod(0o600)
            runner = FakeRunner(initial_rules=[
                {"priority": 0, "table": "local"},
                {"priority": 1061, "fwmark": "0xad61", "table": "880"},
            ])
            helper = SplitTunnelPrivilegedHelper(state_path, runner, lambda: 0, lambda name: "/usr/sbin/nft")
            result = helper.remove()
            self.assertTrue(result["removed"])
            self.assertFalse(state_path.exists())
            self.assertTrue(any(call[0][:3] == ["ip", "rule", "del"] for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ["nft", "delete", "table"] for call in runner.calls))


    def test_remove_keeps_state_and_nft_table_if_ip_rule_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({
                "owner": "adguard-vpn-desktop", "scope": "test.scope",
                "level": 5, "table": 880, "cgroup_path": "/user.slice/user-1000.slice/user@1000.service/app.slice/test.scope", "mark": 0xAD61,
                "priority": 1061, "phase": "active",
            }))
            runner = FakeRunner(
                fail_ip_delete=True,
                initial_rules=[
                    {"priority": 0, "table": "local"},
                    {"priority": 1061, "fwmark": "0xad61", "table": "880"},
                ],
            )
            helper = SplitTunnelPrivilegedHelper(state_path, runner, lambda: 0, lambda name: "/usr/sbin/nft")
            with self.assertRaises(HelperError):
                helper.remove()
            self.assertTrue(state_path.exists())
            self.assertFalse(any(call[0][:3] == ["nft", "delete", "table"] for call in runner.calls))


    def test_remove_keeps_firewall_guards_while_scope_has_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cgroup_path = "/user.slice/user-1000.slice/user@1000.service/app.slice/test.scope"
            cgroup_dir = root.joinpath(*[part for part in cgroup_path.split("/") if part])
            cgroup_dir.mkdir(parents=True)
            process_file = cgroup_dir / "cgroup.procs"
            process_file.write_text("123\\n")
            state_path = root / "state.json"
            state_path.write_text(json.dumps({
                "owner": "adguard-vpn-desktop", "scope": "test.scope",
                "level": 5, "table": 880, "cgroup_path": cgroup_path,
                "mark": 0xAD61, "priority": 1061, "phase": "active",
            }))
            state_path.chmod(0o600)
            runner = FakeRunner(initial_rules=[
                {"priority": 0, "table": "local"},
                {"priority": 1061, "fwmark": "0xad61", "table": "880"},
            ])
            helper = SplitTunnelPrivilegedHelper(
                state_path, runner, lambda: 0, lambda name: "/usr/sbin/nft",
                cgroup_root=root,
            )
            with self.assertRaisesRegex(HelperError, "ещё содержит процессы"):
                helper.remove()
            self.assertTrue(state_path.exists())
            self.assertFalse(any(call[0][:3] == ["nft", "delete", "table"] for call in runner.calls))

            process_file.write_text("")
            result = helper.remove()
            self.assertTrue(result["removed"])
            self.assertFalse(state_path.exists())



if __name__ == "__main__":
    unittest.main()
