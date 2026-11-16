"""Headless tests for desktop application discovery and command parsing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.applications import _exec_tokens, _resolve, discover_apps


class ApplicationDiscoveryTests(unittest.TestCase):
    def test_desktop_field_codes_are_removed(self):
        self.assertEqual(_exec_tokens(f'"{sys.executable}" --open %U'), [sys.executable, "--open"])

    def test_resolve_absolute_executable(self):
        command, reason = _resolve([sys.executable, "-V"])
        self.assertEqual(reason, "")
        self.assertEqual(command, [str(Path(sys.executable).resolve()), "-V"])

    def test_flatpak_resolves_to_flatpak_run_inside_launcher_scope(self):
        with patch("modules.applications.shutil.which", return_value="/usr/bin/flatpak"), patch("modules.applications.subprocess.run") as run:
            run.return_value.returncode = 0
            command, reason = _resolve(["flatpak", "run", "--branch=stable", "org.example.App"])
        self.assertEqual(reason, "")
        self.assertEqual(command, ["/usr/bin/flatpak", "run", "org.example.App"])

    def test_discover_apps_from_xdg_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app_dir = root / "applications"
            app_dir.mkdir()
            desktop = app_dir / "test-app.desktop"
            desktop.write_text(
                "[Desktop Entry]\nType=Application\nName=Telegram Test\n"
                f"Exec={sys.executable} -V %U\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "XDG_DATA_HOME": temp,
                "XDG_DATA_DIRS": temp,
                "LANG": "ru_RU.UTF-8",
            }):
                found = discover_apps()
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["name"], "Telegram Test")
            self.assertTrue(found[0]["supported"])


if __name__ == "__main__":
    unittest.main()
