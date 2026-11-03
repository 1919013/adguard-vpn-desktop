"""Tests for the DNS UI controller without requiring a display server."""
import unittest
from modules.dns import DNSController


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
