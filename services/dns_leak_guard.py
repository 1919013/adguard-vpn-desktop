"""Read-only DNS leak preflight for process-aware VPN routing.

Split tunneling is refused unless the active system resolver uses exactly the
upstream servers supplied by AdGuard VPN CLI and each server routes through
the currently active TUN interface. This check never edits resolver settings.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import struct
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


def _probe_dns_server(server: str, *, timeout: float = 2.5) -> tuple[bool, str]:
    """Send a real DNS A query directly to one upstream and validate its reply."""
    try:
        address = ipaddress.ip_address(server)
        query_id = 0xAD61
        question = b"".join(
            bytes([len(label)]) + label.encode("ascii")
            for label in ("example", "com")
        ) + b"\\x00"
        packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
        packet += question + struct.pack("!HH", 1, 1)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        destination = (server, 53, 0, 0) if family == socket.AF_INET6 else (server, 53)
        with socket.socket(family, socket.SOCK_DGRAM) as client:
            client.settimeout(timeout)
            client.sendto(packet, destination)
            response, _ = client.recvfrom(4096)
        if len(response) < 12:
            return False, "DNS-сервер вернул слишком короткий ответ."
        response_id, flags, questions, _answers, _authority, _additional = struct.unpack(
            "!HHHHHH", response[:12]
        )
        if response_id != query_id or not flags & 0x8000 or questions != 1:
            return False, "Ответ DNS не прошёл проверку идентификатора/формата."
        rcode = flags & 0x000F
        if rcode != 0:
            return False, f"DNS-сервер вернул RCODE={rcode}."
        return True, "DNS-запрос example.com успешно обработан."
    except (OSError, ValueError, struct.error) as exc:
        return False, f"Реальный DNS-запрос не прошёл: {exc}"


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
                 home: Path | None = None,
                 query_probe: Callable[[str], tuple[bool, str]] = _probe_dns_server):
        self.runner = runner
        self.query_probe = query_probe
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
                continue
            probe_ok, probe_detail = self.query_probe(server)
            if not probe_ok:
                reasons.append(f"Проверка реального DNS-запроса к {server} не пройдена: {probe_detail}")

        return {
            "ready": not reasons,
            "servers": cli_servers,
            "reasons": tuple(reasons),
            "real_dns_queries_checked": True,
        }
