"""Tests for per-user GUI autostart without touching the real home directory."""
import tempfile
import unittest
from pathlib import Path

from types import SimpleNamespace

from services.autostart import AutostartManager, VPNCLIAutostartManager


class AutostartTests(unittest.TestCase):
    def test_enable_and_disable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "main.py"
            script.write_text("pass\n", encoding="utf-8")
            entry = root / "config" / "autostart" / "adguard-vpn-desktop.desktop"
            manager = AutostartManager(entry_path=entry, main_path=script)
            self.assertFalse(manager.enabled())
            manager.enable()
            self.assertTrue(manager.enabled())
            content = entry.read_text(encoding="utf-8")
            self.assertIn("Name=ADGuard VPN Desktop", content)
            self.assertIn("Exec=", content)
            self.assertTrue(manager.disable())
            self.assertFalse(manager.enabled())
            self.assertFalse(manager.disable())

    def test_vpn_cli_autostart_requires_and_uses_boot_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "autostart" / "adguard-vpn-cli.desktop"
            calls = []
            def help_runner(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(stdout="connect options: --boot", returncode=0)
            manager = VPNCLIAutostartManager(
                entry_path=entry,
                binary_path="/opt/adguardvpn_cli/adguardvpn-cli",
                help_runner=help_runner,
            )
            self.assertFalse(manager.enabled())
            manager.enable()
            self.assertTrue(manager.enabled())
            self.assertEqual(calls[0][-2:], ["connect", "--help"])
            content = entry.read_text(encoding="utf-8")
            self.assertIn("connect", content)
            self.assertIn("-y", content)
            self.assertIn("--boot", content)
            self.assertTrue(manager.disable())
            self.assertFalse(manager.enabled())

    def test_vpn_cli_autostart_refuses_unsupported_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = VPNCLIAutostartManager(
                entry_path=Path(directory) / "autostart.desktop",
                binary_path="/usr/bin/adguardvpn-cli",
                help_runner=lambda *_args, **_kwargs: SimpleNamespace(
                    stdout="connect options", returncode=0
                ),
            )
            with self.assertRaisesRegex(RuntimeError, "--boot"):
                manager.enable()

    def test_enable_requires_existing_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "autostart.desktop"
            manager = AutostartManager(entry_path=entry, main_path=Path(directory) / "missing.py")
            with self.assertRaises(FileNotFoundError):
                manager.enable()


if __name__ == "__main__":
    unittest.main()
