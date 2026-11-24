import subprocess
import unittest

from services.split_tunnel_watchdog import SplitTunnelWatchdog, active_tunnel


class FakeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class WatchdogTests(unittest.TestCase):
    def test_active_tunnel_requires_connected_cli_status(self):
        runner = lambda args, timeout=8: (0, "Connected to Riga, running on tun0")
        self.assertEqual(active_tunnel(runner), "tun0")
        disconnected = lambda args, timeout=8: (0, "Disconnected")
        self.assertIsNone(active_tunnel(disconnected))

    def test_only_adguard_scopes_are_stopped(self):
        class Runner:
            def __init__(self):
                self.scopes = ["adguard-vpn-chrome.scope", "app-firefox.scope"]
                self.calls = []

            def __call__(self, argv, **kwargs):
                self.calls.append(list(argv))
                if "list-units" in argv:
                    lines = [f"{name} loaded active running" for name in self.scopes]
                    return FakeResult(0, "\n".join(lines))
                if argv[:4] == ["systemctl", "--user", "stop", "adguard-vpn-chrome.scope"]:
                    self.scopes.remove("adguard-vpn-chrome.scope")
                    return FakeResult()
                return FakeResult(1, "unexpected command")

        runner = Runner()
        watchdog = SplitTunnelWatchdog(runner=runner, interval=0.2, stop_timeout=2)
        scopes = watchdog.protected_scopes()
        self.assertEqual(scopes, ["adguard-vpn-chrome.scope"])
        self.assertTrue(watchdog.stop_scopes(scopes))
        stop_calls = [call for call in runner.calls if len(call) > 3 and call[2] == "stop"]
        self.assertEqual(stop_calls, [[
            "systemctl", "--user", "stop", "adguard-vpn-chrome.scope"
        ]])
        self.assertIn("app-firefox.scope", runner.scopes)

    def test_invalid_scope_names_are_never_passed_to_systemctl(self):
        class Runner:
            def __init__(self):
                self.calls = []
            def __call__(self, argv, **kwargs):
                self.calls.append(list(argv))
                return FakeResult()

        runner = Runner()
        watchdog = SplitTunnelWatchdog(runner=runner)
        self.assertTrue(watchdog.stop_scopes(["not-ours.scope", "adguard-vpn-good.scope"]))
        stop = [call for call in runner.calls if "stop" in call]
        self.assertEqual(stop, [[
            "systemctl", "--user", "stop", "adguard-vpn-good.scope"
        ]])

    def test_cleanup_is_retried_after_temporary_polkit_failure(self):
        from unittest.mock import patch

        class Runner:
            def __init__(self):
                self.list_calls = 0
                self.remove_calls = 0

            def __call__(self, argv, **kwargs):
                if "list-units" in argv:
                    self.list_calls += 1
                    if self.list_calls == 1:
                        return FakeResult(0, "adguard-vpn-chrome.scope loaded active running")
                    return FakeResult(0, "")
                if argv and argv[0] == "pkexec":
                    self.remove_calls += 1
                    return FakeResult(1 if self.remove_calls == 1 else 0, "")
                return FakeResult(0, "")

        runner = Runner()
        sleeps = 0

        def stop_after_retry(_interval):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                raise StopIteration()

        watchdog = SplitTunnelWatchdog(
            runner=runner,
            cli_runner=lambda args, timeout=8: (0, "Connected to Riga, running on tun0"),
            interval=0.2,
            sleeper=stop_after_retry,
        )
        with patch("services.split_tunnel_watchdog.shutil.which", return_value="/usr/bin/fake"):
            with self.assertRaises(StopIteration):
                watchdog.run_forever()

        self.assertEqual(runner.remove_calls, 2)


if __name__ == "__main__":
    unittest.main()
