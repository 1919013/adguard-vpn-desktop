"""Headless tests for desktop application discovery and command parsing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.applications import _exec_tokens, _resolve, discover_apps, remove_routing


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


class RoutingRemovalTests(unittest.TestCase):
    def test_launcher_cleanup_failure_keeps_routing_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            routing_state = Path(temp) / "routing-backup.json"
            routing_state.write_text("{}", encoding="utf-8")
            selection_dir = Path(temp) / "selection"
            selection_dir.mkdir()
            selection_state = selection_dir / "routed-apps.json"
            selection_state.write_text("{}", encoding="utf-8")

            with patch("modules.applications.app_routing.state_path", return_value=routing_state), \
                 patch("modules.applications._state_file", return_value=selection_state), \
                 patch("modules.applications._remove_generated_files",
                       return_value=(2, "unexpected managed file")), \
                 patch("modules.applications.app_routing.disable") as disable:
                code, message = remove_routing()

            self.assertEqual(code, 2)
            self.assertIn("настройки VPN не изменены", message)
            self.assertTrue(routing_state.exists())
            self.assertTrue(selection_state.exists())
            disable.assert_not_called()

    def test_successful_removal_cleans_launchers_before_disabling_routing(self):
        with tempfile.TemporaryDirectory() as temp:
            routing_state = Path(temp) / "routing-backup.json"
            routing_state.write_text("{}", encoding="utf-8")
            selection_state = Path(temp) / "routed-apps.json"
            selection_state.write_text("{}", encoding="utf-8")
            calls = []

            def cleanup():
                calls.append("cleanup")
                return 0, "cleaned"

            def disable():
                calls.append("disable")
                return 0, "routing disabled"

            with patch("modules.applications.app_routing.state_path", return_value=routing_state), \
                 patch("modules.applications._state_file", return_value=selection_state), \
                 patch("modules.applications._remove_generated_files", side_effect=cleanup), \
                 patch("modules.applications.app_routing.disable", side_effect=disable):
                code, message = remove_routing()

            self.assertEqual(code, 0, message)
            self.assertEqual(calls, ["cleanup", "disable"])
            self.assertFalse(selection_state.exists())
            self.assertIn("оригинальные ярлыки не затронуты", message)


if __name__ == "__main__":
    unittest.main()
