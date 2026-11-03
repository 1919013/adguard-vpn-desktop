"""Unit tests for DNSManager; no real NetworkManager calls are made."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from services.dns_manager import (
    ADGUARD_DNS, BACKUP_FIELDS, DNSManager, DNSManagerError, TEST_PROFILES,
)


class DNSManagerTests(unittest.TestCase):
    def test_production_profiles_are_rejected(self):
        with self.assertRaises(ValueError):
            DNSManager(profiles=("Wired connection 1",))
        with self.assertRaises(ValueError):
            DNSManager(profiles=("DOD",))

    def test_unknown_test_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            DNSManager(profiles=("ADGuard-DNS-TEST-WIFI-SECURE",))

    def test_dry_run_never_changes_network(self):
        calls = []
        def runner(command, timeout=15):
            calls.append(command)
            if command[:2] == ["adguardvpn-cli", "status"]:
                return 0, "Connected to RIGA in TUN mode, running on tun0"
            if "connection" in command and "show" in command:
                return 0, ""
            return 0, ""
        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=runner)
            result = manager.dry_run()
            self.assertTrue(result["vpn_connected_tun"])
            self.assertFalse(result["changes_made"])
            self.assertFalse(any("modify" in command for command in calls))

    def test_backup_validation_rejects_wrong_profile_set(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=lambda *a, **k: (0, ""))
            manager._ensure_state_dir()
            data = {
                "version": 1, "created": "now",
                "profiles": {TEST_PROFILES[0]: {field: "" for field in BACKUP_FIELDS}},
            }
            manager.backup_file.write_text(json.dumps(data), encoding="utf-8")
            os.chmod(manager.backup_file, 0o600)
            with self.assertRaises(DNSManagerError):
                manager.validate_backup()

    def test_backup_validation_accepts_complete_owned_0600_file(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=lambda *a, **k: (0, ""))
            manager._ensure_state_dir()
            data = {
                "version": 1, "created": "now",
                "profiles": {
                    profile: {field: "" for field in BACKUP_FIELDS}
                    for profile in TEST_PROFILES
                },
            }
            manager.backup_file.write_text(json.dumps(data), encoding="utf-8")
            os.chmod(manager.backup_file, 0o600)
            self.assertEqual(manager.validate_backup(), data)

    def test_dns_constants(self):
        self.assertEqual(ADGUARD_DNS, ("46.243.231.30", "46.243.231.31"))


if __name__ == "__main__":
    unittest.main()
