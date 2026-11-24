"""Fail-closed planner for process-aware VPN routing.

This module only builds a proposed transaction. It never invokes nft, ip,
systemctl, or changes AdGuard VPN CLI configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.process_split_tunnel import (
    DEFAULT_MARK,
    DEFAULT_RULE_PRIORITY,
    SplitTunnelError,
    nft_cgroup_mark_rule,
    policy_rule_command,
)
from services.routing_inspector import RoutingSnapshot


@dataclass(frozen=True)
class SplitTunnelPlan:
    ready: bool
    reasons: tuple[str, ...]
    route_table: int | None
    mark: int
    rule_priority: int | None
    nft_batch: str | None
    ip_rule_add: tuple[str, ...] | None
    ip_rule_delete: tuple[str, ...] | None


def _default_via(route: dict[str, Any], tunnel: str, table: int) -> bool:
    """Require the default route to belong to the exact selected VPN table."""
    dst = route.get("dst", "default")
    route_table = route.get("table")
    return (
        dst in ("default", "0.0.0.0/0", "::/0")
        and route.get("dev") == tunnel
        and str(route_table) == str(table)
    )


def _numeric_table(value: str) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 2**31 - 1 else None


def _fwmark_conflicts(rule: dict[str, Any], mark: int) -> bool:
    raw = rule.get("fwmark")
    if raw is None:
        return False
    try:
        value_text, _, mask_text = str(raw).partition("/")
        value = int(value_text, 0)
        mask = int(mask_text, 0) if mask_text else 0xFFFFFFFF
    except ValueError:
        # An unparseable existing mark is a conflict: fail closed.
        return True
    return (mark & mask) == (value & mask)


def _is_existing_owned_rule(rule: dict[str, Any], mark: int,
                             table: int | None, priority: int) -> bool:
    """Recognize only the exact mark/table/priority tuple owned by this app."""
    if table is None:
        return False
    try:
        raw = str(rule.get("fwmark", ""))
        mark_text, _, mask_text = raw.partition("/")
        value = int(mark_text, 0)
        mask = int(mask_text, 0) if mask_text else 0xFFFFFFFF
        rule_table = str(rule.get("table", rule.get("lookup", "")))
        return (
            value == mark and mask == 0xFFFFFFFF
            and rule_table == str(table)
            and str(rule.get("priority", "")) == str(priority)
        )
    except (TypeError, ValueError):
        return False


def build_split_tunnel_plan(
    snapshot: RoutingSnapshot,
    cgroup_path: str,
    *,
    routing_mode: str,
    dns_policy_ready: bool = False,
    nft_table_absent: bool = False,
    mark: int = DEFAULT_MARK,
    preferred_priority: int = DEFAULT_RULE_PRIORITY,
) -> SplitTunnelPlan:
    """Build a fail-closed plan; readiness requires explicit SCRIPT and DNS."""
    reasons: list[str] = list(snapshot.warnings)
    if not nft_table_absent:
        reasons.append("Не подтверждено отсутствие таблицы nftables adguard_vpn_desktop; создание может затронуть существующую конфигурацию.")
    if not snapshot.connected or not snapshot.tunnel_interface:
        reasons.append("AdGuard VPN CLI не подтвердил активный TUN-туннель.")

    mode = (routing_mode or "").strip().upper()
    if mode != "SCRIPT":
        reasons.append(
            "Для раздельной маршрутизации требуется явно подтверждённый режим SCRIPT; "
            "AUTO может отправлять через VPN весь системный трафик."
        )

    if len(snapshot.vpn_tables) != 1:
        reasons.append("Не удалось однозначно определить одну таблицу маршрутизации AdGuard VPN.")
        table = None
    else:
        table = _numeric_table(snapshot.vpn_tables[0])
        if table is None:
            reasons.append("Номер таблицы VPN не является допустимым числом.")

    tunnel = snapshot.tunnel_interface
    if tunnel and table is not None:
        has_v4 = any(_default_via(route, tunnel, table) for route in snapshot.ipv4_routes)
        has_v6 = any(_default_via(route, tunnel, table) for route in snapshot.ipv6_routes)
        if not has_v4:
            reasons.append(
                f"В таблице VPN {table} не найден IPv4 default route через интерфейс {tunnel}."
            )
        if not has_v6:
            reasons.append(
                f"В таблице VPN {table} не найден IPv6 default route через интерфейс {tunnel}."
            )

    if not dns_policy_ready:
        reasons.append(
            "Политика DNS ещё не реализована: системный резолвер может отправлять "
            "запросы вне cgroup приложения."
        )

    used_priorities = {
        int(rule["priority"]) for rule in snapshot.rules
        if str(rule.get("priority", "")).isdigit()
        and not _is_existing_owned_rule(rule, mark, table, preferred_priority)
    }
    priority = preferred_priority
    while priority in used_priorities and priority < 32000:
        priority += 1
    if priority in used_priorities:
        reasons.append("Не удалось найти свободный приоритет ip rule.")

    if any(
        _fwmark_conflicts(rule, mark)
        and not _is_existing_owned_rule(rule, mark, table, preferred_priority)
        for rule in snapshot.rules
    ):
        reasons.append("Выбранная метка конфликтует с существующим ip rule или его маской.")

    nft_table = "adguard_vpn_desktop"
    nft_chain = "app_output"
    try:
        mark_rule = nft_cgroup_mark_rule(cgroup_path, mark)
    except SplitTunnelError as exc:
        reasons.append(str(exc))
        mark_rule = None

    nft_batch = None
    ip_add = None
    ip_delete = None
    if not reasons and table is not None and mark_rule is not None:
        # The nftables route-type output chain causes a fresh route lookup
        # after setting the packet mark on locally generated application traffic.
        match = " ".join(mark_rule[6:])
        nft_batch = (
            f"add table inet {nft_table}\n"
            f"add chain inet {nft_table} {nft_chain} "
            "{ type route hook output priority mangle; policy accept; }\n"
            f"add rule inet {nft_table} {nft_chain} {match}\n"
        )
        ip_add = tuple(policy_rule_command(mark=mark, table=table, priority=priority))
        ip_delete = (
            "ip", "rule", "del", "priority", str(priority),
            "fwmark", hex(mark), "lookup", str(table),
        )

    return SplitTunnelPlan(
        ready=not reasons and nft_batch is not None and ip_add is not None,
        reasons=tuple(reasons),
        route_table=table,
        mark=mark,
        rule_priority=priority if priority not in used_priorities else None,
        nft_batch=nft_batch,
        ip_rule_add=ip_add,
        ip_rule_delete=ip_delete,
    )
