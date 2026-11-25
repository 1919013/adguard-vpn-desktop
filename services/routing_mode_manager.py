"""Transactional AdGuard VPN CLI routing-mode configuration."""
from __future__ import annotations

import re
from typing import Callable

from core.commands import run_cli


class RoutingModeError(RuntimeError):
    """The requested CLI routing mode could not be applied safely."""


def parse_cli_routing_config(output: str) -> dict:
    text = output or ""
    vpn = re.search(
        r"^\s*(?:VPN\s+)?Mode\s*[:=]\s*(TUN|SOCKS)\b",
        text, re.IGNORECASE | re.MULTILINE,
    )
    routing = re.search(
        r"^\s*(?:(?:VPN|TUN|Tunnel)\s+)?Routing(?:\s+Mode)?\s*[:=]\s*(SCRIPT|AUTO|NONE)\b",
        text, re.IGNORECASE | re.MULTILINE,
    )
    dns = re.search(
        r"^\s*Change\s+system\s+DNS\s*[:=]\s*(on|off|yes|no|true|false)\b",
        text, re.IGNORECASE | re.MULTILINE,
    )
    return {
        "vpn_mode": vpn.group(1).upper() if vpn else None,
        "routing_mode": routing.group(1).upper() if routing else None,
        "change_system_dns": bool(dns and dns.group(1).casefold() in ("on", "yes", "true")),
        "dns_setting_known": dns is not None,
    }


def read_cli_routing_config(runner: Callable = run_cli) -> dict:
    code, output = runner(["config", "show"], timeout=12)
    if code:
        raise RoutingModeError("Не удалось прочитать конфигурацию AdGuard VPN CLI: " + (output or "ошибка CLI"))
    parsed = parse_cli_routing_config(output)
    if not parsed["vpn_mode"] or not parsed["routing_mode"] or not parsed["dns_setting_known"]:
        raise RoutingModeError(
            "Не удалось однозначно распознать режим TUN/SOCKS, маршрутизацию и настройку системного DNS. "
            "Изменения не внесены."
        )
    return parsed


def set_cli_routing_mode(mode: str, runner: Callable = run_cli) -> dict:
    """Set AUTO for all-apps or SCRIPT for per-app mode, with verification/rollback."""
    desired = str(mode).strip().upper()
    if desired not in ("AUTO", "SCRIPT"):
        raise RoutingModeError("Разрешены только режимы AUTO и SCRIPT.")
    before = read_cli_routing_config(runner)
    if before["vpn_mode"] != "TUN":
        raise RoutingModeError("Для режимов AUTO/SCRIPT требуется VPN mode TUN. SOCKS не менялся.")
    if desired == "SCRIPT" and before["routing_mode"] != "SCRIPT":
        # The CLI creates its own script in its configured data directory. Do not
        # overwrite an existing script; an "already exists" response is accepted.
        code, output = runner(["config", "create-route-script"], timeout=20)
        if code and not re.search(r"already exists|already created", output or "", re.IGNORECASE):
            raise RoutingModeError(
                "Не удалось подготовить пользовательский route script для SCRIPT: "
                + (output or "ошибка CLI")
            )

    dns_was_enabled = before["change_system_dns"]
    if not dns_was_enabled:
        code, output = runner(["config", "set-change-system-dns", "on"], timeout=20)
        if code:
            raise RoutingModeError(
                "Не удалось включить системный DNS AdGuard VPN: " + (output or "ошибка CLI")
            )
        after_dns = read_cli_routing_config(runner)
        if not after_dns["change_system_dns"]:
            raise RoutingModeError("CLI не подтвердил включение Change system DNS; маршрутизация не изменена.")

    if before["routing_mode"] == desired:
        return {"vpn_mode": "TUN", "routing_mode": desired, "change_system_dns": True, "changed": False}

    code, output = runner(["config", "set-tun-routing-mode", desired], timeout=20)
    if code:
        if not dns_was_enabled:
            runner(["config", "set-change-system-dns", "off"], timeout=20)
        raise RoutingModeError("CLI не применил режим " + desired + ": " + (output or "ошибка CLI"))

    try:
        verified = read_cli_routing_config(runner)
        if verified["vpn_mode"] != "TUN" or verified["routing_mode"] != desired or not verified["change_system_dns"]:
            raise RoutingModeError(
                f"CLI не подтвердил режим {desired} и системный DNS. "
                "Фактическая конфигурация: " + str(verified)
            )
    except Exception as exc:
        rollback_errors = []
        code, output = runner(
            ["config", "set-tun-routing-mode", before["routing_mode"]],
            timeout=20,
        )
        if code:
            rollback_errors.append("не удалось вернуть режим " + before["routing_mode"] + ": " + output)
        if not dns_was_enabled:
            code, output = runner(["config", "set-change-system-dns", "off"], timeout=20)
            if code:
                rollback_errors.append("не удалось вернуть Change system DNS: off: " + output)
        if rollback_errors:
            raise RoutingModeError(
                f"Проверка режима не пройдена: {exc}. КРИТИЧЕСКИ: " + "; ".join(rollback_errors)
            ) from exc
        raise RoutingModeError(
            f"Проверка режима не пройдена; прежняя конфигурация CLI восстановлена: {exc}"
        ) from exc

    return {
        "vpn_mode": verified["vpn_mode"],
        "routing_mode": verified["routing_mode"],
        "change_system_dns": verified["change_system_dns"],
        "changed": True,
    }
