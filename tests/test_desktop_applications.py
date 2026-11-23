"""Tests for desktop application discovery and filtering."""
import tempfile
import unittest
from pathlib import Path

from services.desktop_applications import (
    _exec_argv, discover_applications, filter_applications,
)


class DesktopApplicationTests(unittest.TestCase):
    def test_exec_parser_preserves_args_and_removes_file_codes(self):
        self.assertEqual(
            _exec_argv('flatpak run --branch=stable com.google.Chrome --new-window %U'),
            ("flatpak", "run", "--branch=stable", "com.google.Chrome", "--new-window"),
        )

    def test_exec_parser_rejects_unknown_field_code(self):
        self.assertEqual(_exec_argv("firefox %Z"), ())

    def test_discovery_reads_flatpak_and_native_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "chrome.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Google Chrome\n"
                "Exec=flatpak run com.google.Chrome %U\n"
                "DBusActivatable=true\n",
                encoding="utf-8",
            )
            (root / "editor.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Text Editor\n"
                "Exec=/usr/bin/gedit --new-window\n",
                encoding="utf-8",
            )
            apps = discover_applications([root], which=lambda name: "/usr/bin/" + name)
            self.assertEqual(len(apps), 2)
            chrome = next(app for app in apps if app.name == "Google Chrome")
            self.assertTrue(chrome.flatpak)
            self.assertTrue(chrome.dbus_activatable)
            self.assertEqual(chrome.exec_argv[:3], ("flatpak", "run", "com.google.Chrome"))

    def test_hidden_user_entry_hides_lower_priority_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user = base / "user"
            system = base / "system"
            user.mkdir()
            system.mkdir()
            (system / "app.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Visible\nExec=/usr/bin/app\n",
                encoding="utf-8",
            )
            (user / "app.desktop").write_text(
                "[Desktop Entry]\nType=Application\nHidden=true\n",
                encoding="utf-8",
            )
            apps = discover_applications([system, user])
            self.assertEqual(apps, [])

    def test_prefix_filter_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename, name, command in (
                ("telegram.desktop", "Telegram", "telegram-desktop"),
                ("telephony.desktop", "Telephony", "telephony"),
                ("chrome.desktop", "Google Chrome", "google-chrome"),
            ):
                (root / filename).write_text(
                    f"[Desktop Entry]\nType=Application\nName={name}\nExec={command}\n",
                    encoding="utf-8",
                )
            apps = discover_applications([root])
            filtered = filter_applications(apps, "tel")
            self.assertEqual({app.name for app in filtered}, {"Telegram", "Telephony"})


if __name__ == "__main__":
    unittest.main()
