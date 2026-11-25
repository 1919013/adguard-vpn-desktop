"""Read-only NetworkManager inventory used by DNS protection.

This module deliberately does not edit connection profiles or active devices.
It discovers physical active devices dynamically; no user-specific connection
names or interface names are hard-coded.
"""
from __future__ import annotations

import subprocess
from typing import Callable


PHYSICAL_TYPES = {"ethernet", "wifi", "wireless"}


class NetworkManagerError(RuntimeError):
    """NetworkManager inventory could not be read safely."""


def _default_runner(argv: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(
            argv, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _unescape_nmcli(value: str) -> str:
    return value.replace(r"\:", ":").replace(r"\\", "\\")


class NetworkManagerInventory:
    """Inspect active physical links and their effective DNS configuration."""

    FIELDS = (
        "GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CONNECTION,"
        "IP4.DNS,IP6.DNS"
    )

    def __init__(self, *, runner: Callable = _default_runner):
        self.runner = runner

    def devices(self) -> list[dict[str, object]]:
        code, output = self.runner([
            "nmcli", "--colors", "no", "--terse", "--escape", "yes",
            "--fields", self.FIELDS, "device", "show",
        ])
        if code:
            raise NetworkManagerError(
                "Не удалось получить состояние NetworkManager: " + (output or "ошибка nmcli")
            )

        records: dict[str, dict[str, object]] = {}
        current_name = None
        for raw in output.splitlines():
            if ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            key, value = key.strip(), _unescape_nmcli(value.strip())
            if key == "GENERAL.DEVICE":
                current_name = value
                records.setdefault(current_name, {
                    "name": current_name, "dns4": [], "dns6": []
                })
            elif current_name is None:
                continue
            elif key.startswith("GENERAL."):
                records[current_name][key.split(".", 1)[1].lower()] = value
            elif key == "IP4.DNS" and value:
                records[current_name]["dns4"].append(value)
            elif key == "IP6.DNS" and value:
                records[current_name]["dns6"].append(value)

        result = []
        for item in records.values():
            kind = str(item.get("type", "")).casefold()
            state = str(item.get("state", ""))
            if kind not in PHYSICAL_TYPES or not state.startswith("100"):
                continue
            result.append({
                "name": str(item["name"]),
                "type": kind,
                "state": state,
                "connection": str(item.get("connection", "")),
                "dns4": tuple(item.get("dns4", [])),
                "dns6": tuple(item.get("dns6", [])),
            })
        return sorted(result, key=lambda item: str(item["name"]))

    def active_physical_devices(self) -> list[dict[str, object]]:
        """Return active Ethernet/Wi-Fi links, excluding TUN, loopback and bridges."""
        return self.devices()
