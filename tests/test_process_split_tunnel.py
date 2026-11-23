"""Tests for process-aware split-tunneling primitives."""
import tempfile
import unittest
from pathlib import Path

from services.process_split_tunnel import (
    SplitTunnelError,
    build_scoped_launch_command,
    cgroup_v2_id,
    is_flatpak_command,
    nft_cgroup_mark_rule,
    policy_rule_command,
    read_process_cgroup,
)


class SplitTunnelPrimitiveTests(unittest.TestCase):
    def test_native_app_is_wrapped_in_user_scope(self):
        self.assertEqual(
            build_scoped_launch_command(["/usr/bin/firefox", "--new-window"], "org.mozilla.firefox"),
            ["systemd-run", "--user", "--scope", "--collect", "--unit",
             "adguard-vpn-org.mozilla.firefox", "--slice", "app.slice", "--",
             "/usr/bin/firefox", "--new-window"],
        )

    def test_flatpak_command_is_wrapped_without_losing_arguments(self):
        command = ["flatpak", "run", "com.google.Chrome", "--incognito"]
        wrapped = build_scoped_launch_command(command, "com.google.Chrome")
        self.assertEqual(wrapped[-4:], command)
        self.assertTrue(is_flatpak_command(command))
        self.assertFalse(is_flatpak_command(["/usr/bin/firefox"]))

    def test_rejects_shell_string_and_empty_command(self):
        for command in ("firefox", [], [""]):
            with self.subTest(command=command), self.assertRaises(SplitTunnelError):
                build_scoped_launch_command(command, "firefox")

    def test_reads_cgroup_v2_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "123"
            proc.mkdir()
            (proc / "cgroup").write_text("0::/user.slice/app.slice/test.scope\n")
            self.assertEqual(read_process_cgroup(123, Path(tmp)), "/user.slice/app.slice/test.scope")

    def test_rejects_invalid_cgroup_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "123"
            proc.mkdir()
            (proc / "cgroup").write_text("0::/../../etc\n")
            with self.assertRaises(SplitTunnelError):
                read_process_cgroup(123, Path(tmp))

    def test_cgroup_id_comes_from_directory_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cgroup.controllers").write_text("cpu memory")
            scope = root / "user.slice" / "test.scope"
            scope.mkdir(parents=True)
            self.assertEqual(cgroup_v2_id("/user.slice/test.scope", root), scope.stat().st_ino)

    def test_rejects_cgroup_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cg"
            root.mkdir()
            with self.assertRaises(SplitTunnelError):
                cgroup_v2_id("/../../etc", root)

    def test_builds_nft_and_ip_rule_commands(self):
        self.assertEqual(
            nft_cgroup_mark_rule("/user.slice/user-1000.slice/user@1000.service/app.slice/adguard-vpn-firefox.scope"),
            ["nft", "add", "rule", "inet", "adguard_vpn_desktop", "app_output",
             "socket", "cgroupv2", "level", "5", "adguard-vpn-firefox.scope",
             "meta", "mark", "set", "0xad61"],
        )
        self.assertEqual(
            policy_rule_command(),
            ["ip", "rule", "add", "priority", "1061", "fwmark", "0xad61", "lookup", "51820"],
        )

    def test_rejects_invalid_kernel_values(self):
        with self.assertRaises(SplitTunnelError):
            nft_cgroup_mark_rule("/not-a-scope")
        with self.assertRaises(SplitTunnelError):
            policy_rule_command(table=0)


if __name__ == "__main__":
    unittest.main()
