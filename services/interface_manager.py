"""Read-only discovery of network interfaces and the AdGuard VPN path.

This service intentionally does not change routes, NetworkManager profiles or DNS.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any


class InterfaceDiscoveryError(RuntimeError):
    """Raised when the host network state cannot be inspected."""


def _run(command: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


class InterfaceManager:
    """Discover interfaces and report the currently observed VPN tunnel."""

    def __init__(self, runner=_run):
        self.runner = runner

    def list_interfaces(self) -> list[dict[str, Any]]:
        code, output = self.runner(["ip", "-j", "-details", "address", "show"])
        if code:
            raise InterfaceDiscoveryError("Не удалось прочитать интерфейсы через ip: " + output)
        try:
            raw = json.loads(output or "[]")
        except json.JSONDecodeError as exc:
            raise InterfaceDiscoveryError("Команда ip вернула некорректный JSON") from exc

        devices: dict[str, str] = {}
        nm_code, nm_output = self.runner([
            "nmcli", "--colors", "no", "--terse",
            "--fields", "DEVICE,TYPE,STATE,CONNECTION", "device", "status",
        ])
        if nm_code == 0:
            for line in nm_output.splitlines():
                fields = line.split(":")
                if fields:
                    # nmcli escapes colons in values; device names themselves cannot contain one.
                    devices[fields[0]] = " · ".join(fields[1:])

        result = []
        for item in raw:
            name = item.get("ifname")
            if not name or name == "lo":
                continue
            flags = item.get("flags") or []
            addresses = []
            for info in item.get("addr_info") or []:
                local = info.get("local")
                prefix = info.get("prefixlen")
                if local:
                    addresses.append(f"{local}/{prefix}" if prefix is not None else str(local))
            result.append({
                "name": name,
                "state": "UP" if "UP" in flags else "DOWN",
                "kind": (item.get("linkinfo") or {}).get("info_kind", item.get("link_type", "обычный")),
                "addresses": addresses,
                "network_manager": devices.get(name, "не управляется NetworkManager или недоступен"),
            })
        return result

    def adguard_path(self) -> dict[str, str | bool]:
        code, output = self.runner(["adguardvpn-cli", "status"])
        clean = re.sub(r"\x1b\[[0-9;]*m", "", output or "")
        match = re.search(r"running on ([A-Za-z0-9_.:-]+)", clean, re.IGNORECASE)
        if code == 0 and match:
            return {"connected": True, "interface": match.group(1), "detail": clean}
        return {
            "connected": False,
            "interface": "",
            "detail": clean or "Не удалось получить статус AdGuard VPN CLI.",
        }
