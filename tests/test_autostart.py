"""Tests for per-user GUI autostart without touching the real home directory."""
import tempfile
import unittest
from pathlib import Path

from services.autostart import AutostartManager


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

    def test_enable_requires_existing_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "autostart.desktop"
            manager = AutostartManager(entry_path=entry, main_path=Path(directory) / "missing.py")
            with self.assertRaises(FileNotFoundError):
                manager.enable()


if __name__ == "__main__":
    unittest.main()
