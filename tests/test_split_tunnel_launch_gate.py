"""Tests for the launch gate's fail-closed ordering."""
import unittest

from services.split_tunnel_launch_gate import (
    LaunchGateError, _apply_verify_release,
)


class LaunchGateOrderingTests(unittest.TestCase):
    def test_release_occurs_only_after_apply_and_live_verification(self):
        events = []
        _apply_verify_release(
            "/user.slice/app.slice/test.scope",
            lambda path: events.append(("apply", path)),
            lambda path: events.append(("verify", path)) or True,
            lambda: events.append(("release",)),
            lambda: events.append(("abort",)),
        )
        self.assertEqual([event[0] for event in events], ["apply", "verify", "release"])

    def test_failed_verification_aborts_and_never_releases(self):
        events = []
        with self.assertRaises(LaunchGateError):
            _apply_verify_release(
                "/user.slice/app.slice/test.scope",
                lambda path: events.append(("apply", path)),
                lambda path: events.append(("verify", path)) or False,
                lambda: events.append(("release",)),
                lambda: events.append(("abort",)),
            )
        self.assertEqual([event[0] for event in events], ["apply", "verify", "abort"])

    def test_apply_failure_aborts_and_never_verifies_or_releases(self):
        events = []
        def fail(_path):
            events.append(("apply",))
            raise RuntimeError("simulated helper failure")
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            _apply_verify_release(
                "/user.slice/app.slice/test.scope", fail,
                lambda path: events.append(("verify", path)) or True,
                lambda: events.append(("release",)),
                lambda: events.append(("abort",)),
            )
        self.assertEqual([event[0] for event in events], ["apply", "abort"])


if __name__ == "__main__":
    unittest.main()
