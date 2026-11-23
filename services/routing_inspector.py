"""Read-only discovery of the live AdGuard VPN routing table."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable, Any

from services.interface_manager import InterfaceManager


@dataclass(frozen=True)
class RoutingSnapshot:
    connected: bool
    tunnel_interface: str
    vpn_tables: tuple[str, ...]
    ipv4_routes: tuple[dict[str, Any], ...]
    ipv6_routes: tuple[dict[str, Any], ...]
    rules: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


class RoutingInspector:
    """Inspect Linux policy routing without changing routes or CLI settings."""

    def __init__(self, runner: Callable[..., tuple[int, str]] | None = None,
                 interface_manager: InterfaceManager | None = None):
        self.runner = runner or self._run
        self.interface_manager = interface_manager or InterfaceManager(runner=self.runner)

    @staticmethod
    def _run(command: list[str], timeout: int = 8) -> tuple[int, str]:
        try:
            result = subprocess.run(
                command, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=timeout, check=False,
            )
            return result.returncode, result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)

    def _json(self, command: list[str]) -> tuple[list[dict[str, Any]] | None, str | None]:
        code, output = self.runner(command, timeout=8)
        if code:
            return None, output or f"Команда завершилась с кодом {code}"
        try:
            value = json.loads(output or "[]")
        except json.JSONDecodeError:
            return None, "Команда ip вернула некорректный JSON."
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            return None, "Неожиданный формат JSON от ip."
        return value, None

    def inspect(self) -> RoutingSnapshot:
        path = self.interface_manager.adguard_path()
        warnings: list[str] = []
        if path.get("connected"):
            tunnel = str(path.get("interface", ""))
        else:
            tunnel = ""
            warnings.append("AdGuard VPN CLI не подтвердил активный TUN-туннель.")

        v4, error4 = self._json(["ip", "-j", "-4", "route", "show", "table", "all"])
        v6, error6 = self._json(["ip", "-j", "-6", "route", "show", "table", "all"])
        rules, error_rules = self._json(["ip", "-j", "rule", "show"])
        for error in (error4, error6, error_rules):
            if error:
                warnings.append(error)

        v4 = v4 or []
        v6 = v6 or []
        rules = rules or []
        tables: set[str] = set()
        if tunnel:
            for route in [*v4, *v6]:
                destination = route.get("dst", "default")
                if route.get("dev") == tunnel and destination in ("default", "0.0.0.0/0", "::/0"):
                    table = route.get("table")
                    if table is not None:
                        tables.add(str(table))
            if not tables:
                warnings.append(
                    "Не найдена таблица с default route через активный TUN. "
                    "Режим маршрутизации может быть NONE или SCRIPT без настроенной таблицы."
                )

        return RoutingSnapshot(
            connected=bool(path.get("connected")),
            tunnel_interface=tunnel,
            vpn_tables=tuple(sorted(tables)),
            ipv4_routes=tuple(v4),
            ipv6_routes=tuple(v6),
            rules=tuple(rules),
            warnings=tuple(warnings),
        )
