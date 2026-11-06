"""Unit tests for DNS manager and its UI-independent controller."""
import json
import os
import tempfile
import unittest

from modules.dns import DNSController
from services.dns_manager import (
    ADGUARD_DNS, BACKUP_FIELDS, DNSManager, DNSManagerError, TEST_PROFILES,
)


class FakeManager:
    def status(self):
        return {"vpn_connected_tun": True, "vpn_output": "connected", "profiles": {}}
    def dry_run(self):
        return {"changes_made": False}
    def create_backup(self):
        return "/tmp/test-backup.json"
    def apply_adguard_dns(self):
        self.applied = True
    def validate_backup(self):
        return {"created": "today", "profiles": {}}
    def restore(self):
        self.restored = True


class DNSManagerTests(unittest.TestCase):
    def test_unknown_profiles_are_rejected(self):
        for profile in ("custom-wired-profile", "custom-wifi-profile"):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    DNSManager(profiles=(profile,))

    def test_unknown_test_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            DNSManager(profiles=("unapproved-user-profile",))

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
                "version": 1,
                "created": "now",
                "profiles": {
                    TEST_PROFILES[0]: {field: "" for field in BACKUP_FIELDS}
                },
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
                "version": 1,
                "created": "now",
                "profiles": {
                    profile: {field: "" for field in BACKUP_FIELDS}
                    for profile in TEST_PROFILES
                },
            }
            manager.backup_file.write_text(json.dumps(data), encoding="utf-8")
            os.chmod(manager.backup_file, 0o600)
            self.assertEqual(manager.validate_backup(), data)

    def test_dns_lock_rejects_insecure_existing_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=lambda *a, **k: (0, ""))
            manager._ensure_state_dir()
            manager.lock_file.write_text("", encoding="utf-8")
            os.chmod(manager.lock_file, 0o644)
            with self.assertRaisesRegex(DNSManagerError, "permissions must be 0600"):
                manager._locked()

    def test_backup_creation_respects_dns_operation_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=lambda *a, **k: (0, ""))
            lock_fd = manager._locked()
            try:
                with self.assertRaisesRegex(DNSManagerError, "already running"):
                    manager.create_backup()
            finally:
                os.close(lock_fd)

    def test_apply_refuses_to_change_network_without_backup(self):
        calls = []
        def runner(command, timeout=15):
            calls.append(command)
            if command[:2] == ["adguardvpn-cli", "status"]:
                return 0, "Connected to TEST in TUN mode, running on tun0"
            if "connection" in command and "show" in command:
                return 0, ""
            return 0, ""
        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=runner)
            with self.assertRaisesRegex(DNSManagerError, "valid DNS backup"):
                manager.apply_adguard_dns()
            self.assertFalse(any("modify" in command for command in calls))

    def test_apply_refuses_stale_backup(self):
        calls = []
        def runner(command, timeout=15):
            calls.append(command)
            if command[:2] == ["adguardvpn-cli", "status"]:
                return 0, "Connected to TEST in TUN mode, running on tun0"
            if "connection" in command and "show" in command and "--active" in command:
                return 0, ""
            if "connection" in command and "show" in command:
                fields = command[command.index("--fields") + 1].split(",")
                return 0, "\n".join(
                    f"{field}:" + ("8.8.8.8" if field == "ipv4.dns" else "")
                    for field in fields
                )
            return 0, ""

        with tempfile.TemporaryDirectory() as directory:
            manager = DNSManager(state_dir=directory, runner=runner)
            manager._ensure_state_dir()
            saved = {
                profile: {field: "" for field in BACKUP_FIELDS}
                for profile in TEST_PROFILES
            }
            saved[TEST_PROFILES[0]]["ipv4.dns"] = "1.1.1.1"
            manager.backup_file.write_text(
                json.dumps({"version": 1, "created": "now", "profiles": saved}),
                encoding="utf-8",
            )
            os.chmod(manager.backup_file, 0o600)
            with self.assertRaisesRegex(DNSManagerError, "does not match current settings"):
                manager.apply_adguard_dns()
            self.assertFalse(any("modify" in command for command in calls))

    def test_dns_constants(self):
        self.assertEqual(ADGUARD_DNS, ("46.243.231.30", "46.243.231.31"))


class DNSControllerTests(unittest.TestCase):
    def test_controller_delegates_status(self):
        controller = DNSController(FakeManager())
        self.assertTrue(controller.get_status()["vpn_connected_tun"])

    def test_controller_delegates_dry_run(self):
        controller = DNSController(FakeManager())
        self.assertFalse(controller.get_dry_run()["changes_made"])

    def test_controller_delegates_backup(self):
        controller = DNSController(FakeManager())
        self.assertEqual(controller.create_backup(), "/tmp/test-backup.json")

    def test_controller_delegates_apply_and_restore(self):
        manager = FakeManager()
        controller = DNSController(manager)
        controller.apply()
        controller.restore()
        self.assertTrue(manager.applied)
        self.assertTrue(manager.restored)


if __name__ == "__main__":
    unittest.main()
