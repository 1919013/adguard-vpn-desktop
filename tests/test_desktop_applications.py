"""Tests for desktop application discovery and filtering."""
import tempfile
import unittest
from pathlib import Path

from services.process_split_tunnel import SplitTunnelError

from services.desktop_applications import (
    _exec_argv, discover_applications, filter_applications, build_scoped_application_command,
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

    def test_scoped_command_preserves_flatpak_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "chrome.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Chrome\n"
                "Exec=flatpak run com.google.Chrome --incognito\n",
                encoding="utf-8",
            )
            app = discover_applications([root])[0]
            command = build_scoped_application_command(app)
            self.assertEqual(command[-4:], ["flatpak", "run", "com.google.Chrome", "--incognito"])
            self.assertIn("--scope", command)

    def test_refuses_dbus_activation_for_scoped_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dbus.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=DBus App\n"
                "Exec=example-app\nDBusActivatable=true\n",
                encoding="utf-8",
            )
            app = discover_applications([root])[0]
            with self.assertRaises(SplitTunnelError):
                build_scoped_application_command(app)

    def test_custom_executable_path_requires_executable_file(self):
        from services.desktop_applications import custom_application_from_path
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "custom-app"
            binary.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
            binary.chmod(0o755)
            app = custom_application_from_path(str(binary))
            self.assertEqual(app.exec_argv, (str(binary.resolve()),))
            self.assertTrue(app.desktop_id.startswith("custom-"))
            with self.assertRaises(SplitTunnelError):
                custom_application_from_path(str(Path(tmp) / "missing"))


if __name__ == "__main__":
    unittest.main()
