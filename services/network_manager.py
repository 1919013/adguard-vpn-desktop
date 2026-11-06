"""Read-only NetworkManager discovery.

This module discovers the current machine's devices and connection profiles.
It deliberately does not modify profiles or activate/deactivate interfaces.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable

Runner = Callable[..., tuple[int, str]]


def _run_nmcli(args: list[str], timeout: int = 12) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["nmcli", "--colors", "no", "--terse", "--escape", "yes", *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _split_terse(line: str) -> list[str]:
    """Split nmcli terse output while honoring escaped separators."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


class NetworkManagerService:
    """Discover devices and profiles without changing network configuration."""

    def __init__(self, runner: Runner = _run_nmcli):
        self.runner = runner

    def _run(self, args: list[str]) -> tuple[int, str]:
        return self.runner(args)

    def devices(self) -> list[dict[str, str]]:
        code, output = self._run(["device", "status"])
        if code:
            raise RuntimeError(f"Не удалось получить сетевые интерфейсы: {output}")
        lines = output.splitlines()
        devices = []
        for line in lines[1:]:
            fields = _split_terse(line)
            if len(fields) < 4:
                continue
            name, kind, state, connection = fields[:4]
            if not name or name == "lo":
                continue
            devices.append({
                "name": name, "type": kind, "state": state,
                "connection": connection if connection != "--" else "",
            })
        return devices

    def profiles(self) -> list[dict[str, str]]:
        code, output = self._run(["connection", "show"])
        if code:
            raise RuntimeError(f"Не удалось получить профили NetworkManager: {output}")
        profiles = []
        for line in output.splitlines()[1:]:
            fields = _split_terse(line)
            if len(fields) < 4:
                continue
            name, uuid, kind, device = fields[:4]
            profiles.append({
                "name": name, "uuid": uuid, "type": kind,
                "device": "" if device == "--" else device,
            })
        return profiles

    def snapshot(self) -> dict:
        """Return a fresh snapshot; no settings are changed."""
        return {"devices": self.devices(), "profiles": self.profiles()}
