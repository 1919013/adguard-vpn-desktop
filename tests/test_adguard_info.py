"""Tests for safe interactive AdGuard VPN CLI installation."""
import subprocess
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


if __name__ == "__main__":
    unittest.main()
