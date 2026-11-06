"""Read-only IP routing and DNS configuration diagnostics."""
from __future__ import annotations

import subprocess
from collections.abc import Callable

Runner = Callable[..., tuple[int, str]]


def _run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


class NetworkDiagnostics:
    """Collect local routing and configured DNS information without network changes."""

    def __init__(self, runner: Runner = _run):
        self.runner = runner

    def collect(self) -> dict[str, tuple[int, str]]:
        commands = {
            "addresses": ["ip", "-brief", "address"],
            "ipv4_default_route": ["ip", "-4", "route", "show", "default"],
            "ipv6_default_route": ["ip", "-6", "route", "show", "default"],
            "ipv4_route_probe": ["ip", "-4", "route", "get", "1.1.1.1"],
            "ipv6_route_probe": [
                "ip", "-6", "route", "get", "2606:4700:4700::1111",
            ],
            "dns_by_device": [
                "nmcli", "--colors", "no", "--fields",
                "GENERAL.DEVICE,IP4.DNS,IP6.DNS", "device", "show",
            ],
            "resolv_conf": ["cat", "/etc/resolv.conf"],
        }
        result = {}
        for key, command in commands.items():
            result[key] = self.runner(command)
        return result
