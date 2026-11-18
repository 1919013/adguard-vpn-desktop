"""Tests for safe interactive AdGuard VPN CLI installation."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import adguard_info


class InstallerTerminalTests(unittest.TestCase):
    @patch("modules.adguard_info.subprocess.run")
    @patch("modules.adguard_info.shutil.which")
    def test_prefers_debian_terminal_and_does_not_capture_password_prompt(self, which, run):
        which.side_effect = lambda name: {
            "x-terminal-emulator": "/usr/bin/x-terminal-emulator",
            "gnome-terminal": "/usr/bin/gnome-terminal",
        }.get(name)
        run.return_value = Mock(returncode=0)

        code, message = adguard_info._run_installer_in_terminal(Path("/tmp/installer.sh"))

        self.assertEqual(code, 0)
        self.assertIn("символы пароля могут не отображаться", message)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0:3], ["/usr/bin/x-terminal-emulator", "-e", "sh"])
        self.assertEqual(args[0][-1], "/tmp/installer.sh")
        self.assertNotIn("stdout", kwargs)
        self.assertNotIn("stderr", kwargs)
        self.assertNotIn("input", kwargs)
        self.assertEqual(kwargs["timeout"], 900)

    @patch("modules.adguard_info.shutil.which", return_value=None)
    def test_does_not_run_installer_without_supported_terminal(self, _which):
        with patch("modules.adguard_info.subprocess.run") as run:
            code, message = adguard_info._run_installer_in_terminal(Path("/tmp/installer.sh"))
        self.assertEqual(code, 127)
        self.assertIn("Установщик не запускался", message)
        run.assert_not_called()

    @patch("modules.adguard_info.subprocess.run", side_effect=subprocess.TimeoutExpired("terminal", 900))
    @patch("modules.adguard_info.shutil.which", side_effect=lambda name: "/usr/bin/x-terminal-emulator" if name == "x-terminal-emulator" else None)
    def test_reports_terminal_timeout(self, _which, _run):
        code, message = adguard_info._run_installer_in_terminal(Path("/tmp/installer.sh"))
        self.assertEqual(code, 124)
        self.assertIn("истекло", message)


class UserDataSafetyTests(unittest.TestCase):
    def test_refuses_to_delete_user_data_while_vpn_is_connected(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            config = Path(temp) / "config"
            cache = Path(temp) / "cache"
            target = data / "adguardvpn-cli"
            target.mkdir(parents=True)
            marker = target / "account"
            marker.write_text("preserve", encoding="utf-8")
            with patch.dict(os.environ, {
                "XDG_DATA_HOME": str(data),
                "XDG_CONFIG_HOME": str(config),
                "XDG_CACHE_HOME": str(cache),
            }), patch("modules.adguard_info.run_vpn",
                      return_value=(0, "Connected to RIGA in TUN mode, running on tun0")):
                code, message = adguard_info.clear_user_data()
            self.assertEqual(code, 2)
            self.assertIn("Сначала отключите", message)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_refuses_to_delete_user_data_when_vpn_status_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            target = data / "adguardvpn-cli"
            target.mkdir(parents=True)
            marker = target / "account"
            marker.write_text("preserve", encoding="utf-8")
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(data)}), \
                 patch("modules.adguard_info.run_vpn", return_value=(1, "CLI unavailable")):
                code, message = adguard_info.clear_user_data()
            self.assertEqual(code, 1)
            self.assertIn("данные не удалены", message)
            self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
