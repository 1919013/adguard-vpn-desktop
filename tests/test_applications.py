"""Tests for the read-only desktop application catalogue."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.applications import discover_applications


class ApplicationCatalogueTests(unittest.TestCase):
    def test_discovers_visible_desktop_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            app_dir = Path(directory) / "applications"
            app_dir.mkdir()
            (app_dir / "telegram.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Telegram\n"
                "Exec=telegram-desktop %u\n",
                encoding="utf-8",
            )
            (app_dir / "hidden.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Hidden app\n"
                "Exec=hidden-app\nNoDisplay=true\n",
                encoding="utf-8",
            )
            with patch("modules.applications._desktop_dirs", return_value=[app_dir]):
                result = discover_applications()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "Telegram")
            self.assertEqual(result[0]["exec"], "telegram-desktop %u")

    def test_empty_catalogue_is_allowed(self):
        with patch("modules.applications._desktop_dirs", return_value=[]):
            self.assertEqual(discover_applications(), [])


if __name__ == "__main__":
    unittest.main()
