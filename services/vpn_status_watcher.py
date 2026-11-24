"""Fail-closed polling watcher for the AdGuard VPN CLI connection."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable

from core.commands import run_cli


class VPNStatusWatcher:
    """Set a cancellation event when the CLI no longer confirms the same TUN."""

    def __init__(self, runner: Callable = run_cli, interval: float = 0.5):
        self.runner = runner
        self.interval = max(0.2, float(interval))

    @staticmethod
    def _active_interface(code: int, output: str) -> str | None:
        if code != 0:
            return None
        clean = re.sub(r"\x1b\[[0-9;]*m", "", output or "")
        match = re.search(r"running on ([A-Za-z0-9_.:-]+)", clean, re.IGNORECASE)
        return match.group(1) if match and "Connected to " in clean else None

    def start(self, expected_interface: str):
        cancelled = threading.Event()
        stopped = threading.Event()

        def monitor():
            while not stopped.wait(self.interval):
                code, output = self.runner(["status"], timeout=8)
                current = self._active_interface(code, output)
                if current != expected_interface:
                    cancelled.set()
                    stopped.set()
                    return

        thread = threading.Thread(
            target=monitor, name="adguard-vpn-status-watch", daemon=True
        )
        # Check once synchronously before the application is released.
        code, output = self.runner(["status"], timeout=8)
        if self._active_interface(code, output) != expected_interface:
            cancelled.set()
            stopped.set()
        else:
            thread.start()

        class Watch:
            cancel_event = cancelled
            def stop(self):
                stopped.set()
                if thread.is_alive():
                    thread.join(timeout=1.5)

        return Watch()
