"""Read-only DNS leak preflight for process-aware VPN routing.

Split tunneling is refused unless the active system resolver uses exactly the
upstream servers supplied by AdGuard VPN CLI and each server routes through
the currently active TUN interface. This check never edits resolver settings.
"""
from __future__ import annotations

import ipaddress
import os
import re
import subprocess
from pathlib import Path
from typing import Callable


def _default_runner(argv: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        result = subprocess.run(
            argv, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _nameservers(text: str) -> tuple[str, ...]:
    result = []
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and fields[0].casefold() == "nameserver":
            try:
                result.append(str(ipaddress.ip_address(fields[1])))
            except ValueError:
                continue
    return tuple(dict.fromkeys(result))


class DNSLeakGuard:
    """Verify resolver configuration and route without modifying the host."""

    def __init__(self, *, runner: Callable = _default_runner,
                 resolv_conf: Path = Path("/etc/resolv.conf"),
                 cli_resolv_conf: Path | None = None,
                 home: Path | None = None):
        self.runner = runner
        self.resolv_conf = Path(resolv_conf)
        base = Path(home or Path.home())
        data_home = Path(os.environ.get("XDG_DATA_HOME", base / ".local/share"))
        self.cli_resolv_conf = Path(
            cli_resolv_conf or data_home / "adguardvpn-cli" / "resolv.conf"
        )

    def inspect(self, tunnel_interface: str) -> dict:
        reasons = []
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", tunnel_interface or ""):
            return {"ready": False, "servers": (), "reasons": ("Не определён безопасный TUN-интерфейс.",)}
        try:
            cli_text = self.cli_resolv_conf.read_text(encoding="utf-8")
            active_text = self.resolv_conf.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ready": False, "servers": (), "reasons": (f"Не удалось прочитать DNS-конфигурацию: {exc}",)}

        cli_servers = _nameservers(cli_text)
        active_servers = _nameservers(active_text)
        if not cli_servers:
            reasons.append("В resolv.conf AdGuard VPN CLI не обнаружены DNS-серверы.")
        if not active_servers:
            reasons.append("В системном /etc/resolv.conf не обнаружены DNS-серверы.")
        if any(server in {"127.0.0.53", "127.0.0.1", "::1"} for server in active_servers):
            reasons.append("Обнаружен локальный DNS-stub; upstream systemd-resolved/dnsmasq пока не проверяется безопасно.")
        if set(active_servers) != set(cli_servers):
            reasons.append("Системные DNS-серверы не совпадают с DNS-серверами AdGuard VPN CLI.")

        for server in cli_servers:
            family = "-6" if ":" in server else "-4"
            code, output = self.runner(["ip", "-j", family, "route", "get", server])
            if code:
                reasons.append(f"Не удалось проверить маршрут до DNS-сервера {server}: {output}")
                continue
            try:
                import json
                routes = json.loads(output or "[]")
                devs = {item.get("dev") for item in routes if isinstance(item, dict)}
            except (ValueError, TypeError):
                devs = set()
            if devs != {tunnel_interface}:
                reasons.append(f"DNS-сервер {server} не подтверждён через {tunnel_interface} (маршрут: {', '.join(sorted(str(x) for x in devs)) or 'неизвестен'}).")

        return {
            "ready": not reasons,
            "servers": cli_servers,
            "reasons": tuple(reasons),
        }
