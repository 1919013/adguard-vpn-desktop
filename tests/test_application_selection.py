"""Tests for persisted application selection."""
import json
import tempfile
import unittest
from pathlib import Path

from services.application_selection import load_selection, save_selection, selection_path


class ApplicationSelectionTests(unittest.TestCase):
    def test_selection_path_uses_xdg_config_home(self):
        self.assertEqual(
            selection_path({"XDG_CONFIG_HOME": "/tmp/user-config"}),
            Path("/tmp/user-config/adguard-vpn-desktop/applications.json"),
        )

    def test_round_trip_deduplicates_and_sorts_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config" / "applications.json"
            save_selection(
                ["org.example.App", "org.example.App", "custom-/opt/tool"],
                ["/opt/tool", "/opt/tool"],
                target,
            )
            loaded = load_selection(target)
            self.assertEqual(
                loaded,
                {
                    "selected_ids": ["custom-/opt/tool", "org.example.App"],
                    "custom_paths": ["/opt/tool"],
                },
            )
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)

    def test_missing_file_is_empty_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                load_selection(Path(tmp) / "missing.json"),
                {"selected_ids": [], "custom_paths": []},
            )

    def test_unknown_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "applications.json"
            target.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_selection(target)

    def test_invalid_custom_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "applications.json"
            target.write_text(
                json.dumps({
                    "schema_version": 1,
                    "selected_ids": [],
                    "custom_paths": ["relative/path"],
                }),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_selection(target)


if __name__ == "__main__":
    unittest.main()
