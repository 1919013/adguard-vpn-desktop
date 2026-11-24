"""Independent user-systemd watchdog for protected application scopes.

This process is intentionally separate from the GTK process. It keeps running
if the GUI exits and stops only ADGuard-owned scopes when the CLI disconnects
or changes its TUN interface. Kernel egress guards remain the final backstop.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from typing import Callable

from core.commands import run_cli

HELPER = "/usr/libexec/adguard-vpn-desktop-helper"
SCOPE_PREFIX = "adguard-vpn-"


def active_tunnel(runner: Callable = run_cli) -> str | None:
    code, output = runner(["status"], timeout=8)
    if code:
        return None
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output or "")
    match = re.search(r"running on ([A-Za-z0-9_.:-]+)", clean, re.IGNORECASE)
    if not match or "Connected to " not in clean:
        return None
    return match.group(1)


class SplitTunnelWatchdog:
    """Monitor protected scopes without depending on the GUI supervisor."""

    def __init__(self, *, runner=subprocess.run, cli_runner=run_cli,
                 interval: float = 0.5, stop_timeout: float = 12.0,
                 sleeper: Callable = time.sleep):
        self.runner = runner
        self.cli_runner = cli_runner
        self.interval = max(0.2, float(interval))
        self.stop_timeout = max(2.0, float(stop_timeout))
        self.sleeper = sleeper

    def _run(self, argv: list[str], timeout: int = 10) -> tuple[int, str]:
        try:
            result = self.runner(
                argv, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                timeout=timeout, check=False,
            )
            return int(result.returncode), (result.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)

    def protected_scopes(self) -> list[str]:
        code, output = self._run([
            "systemctl", "--user", "list-units", "--type=scope",
            "--state=running", "--no-legend", "--plain",
        ])
        if code:
            return []
        scopes = []
        for line in output.splitlines():
            fields = line.split()
            if fields and fields[0].startswith(SCOPE_PREFIX) and fields[0].endswith(".scope"):
                scopes.append(fields[0])
        return sorted(set(scopes))

    def stop_scopes(self, scopes: list[str]) -> bool:
        """Stop only scopes with our fixed prefix; never stop app.slice globally."""
        safe = [
            name for name in scopes
            if re.fullmatch(r"adguard-vpn-[A-Za-z0-9_.@-]+\.scope", name)
        ]
        if not safe:
            return True
        self._run(["systemctl", "--user", "stop", *safe], timeout=20)
        deadline = time.monotonic() + self.stop_timeout
        while time.monotonic() < deadline:
            remaining = set(self.protected_scopes())
            if not remaining.intersection(safe):
                return True
            self.sleeper(self.interval)
        return False

    def remove_owned_policy(self) -> bool:
        """Ask the fixed polkit helper to remove state only after scopes exit."""
        if not shutil.which("pkexec") or not shutil.which("systemctl"):
            return False
        code, _ = self._run(["pkexec", HELPER, "remove"], timeout=35)
        return code == 0

    def run_forever(self) -> int:
        expected_tunnel = None
        previously_had_scopes = False
        cleanup_pending = False
        while True:
            scopes = self.protected_scopes()
            if not scopes:
                if previously_had_scopes:
                    # The GUI may have crashed before its cleanup callback.
                    cleanup_pending = True
                previously_had_scopes = False
                expected_tunnel = None
                if cleanup_pending and self.remove_owned_policy():
                    cleanup_pending = False
                self.sleeper(self.interval)
                continue
            previously_had_scopes = True

            current_tunnel = active_tunnel(self.cli_runner)
            if expected_tunnel is None:
                expected_tunnel = current_tunnel
            if current_tunnel is None or current_tunnel != expected_tunnel:
                stopped = self.stop_scopes(scopes)
                if stopped and not self.protected_scopes():
                    cleanup_pending = True
                    if self.remove_owned_policy():
                        cleanup_pending = False
                expected_tunnel = None
                self.sleeper(self.interval)
                continue
            self.sleeper(self.interval)


def main() -> int:
    return SplitTunnelWatchdog().run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
