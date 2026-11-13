"""Linux per-application TUN routing primitives.

This module deliberately separates planning from privileged execution.  The
first implementation phase supports the "VPN only selected apps" direction.
It never changes routes, nftables, or AdGuard CLI settings by itself.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

NFT_TABLE = "adguard_vpn_desktop"
NFT_CHAIN = "app_output"
APP_SLICE = "adguard-vpn-apps.slice"
FWMARK = "0xAD61"
ROUTE_TABLE = "51861"
RULE_PRIORITY = "10610"


class RoutingError(RuntimeError):
    """Raised when the host cannot safely support app-level routing."""


def cgroup_level_for_slice(cgroup_path: str, slice_name: str = APP_SLICE) -> int:
    """Return nft socket-cgroupv2 level for a named cgroup component."""
    parts = [part for part in cgroup_path.strip("/").split("/") if part]
    if slice_name not in parts:
        parts.append(slice_name)
    return parts.index(slice_name) + 1


def current_user_cgroup_path() -> str:
    """Read the current process cgroup v2 path without invoking a shell."""
    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
            if line.startswith("0::"):
                return line[3:]
    except OSError as exc:
        raise RoutingError(f"Не удалось прочитать cgroup v2: {exc}") from exc
    raise RoutingError("Не обнаружена иерархия cgroup v2 (ожидается unified hierarchy).")


def nft_ruleset(cgroup_level: int) -> str:
    """Build an nftables ruleset scoped to this application's own table."""
    if not 1 <= int(cgroup_level) <= 32:
        raise ValueError("Недопустимый уровень cgroup.")
    return (
        f"table inet {NFT_TABLE} {{\n"
        f"  chain {NFT_CHAIN} {{\n"
        "    type route hook output priority mangle; policy accept;\n"
        f'    socket cgroupv2 level {int(cgroup_level)} "{APP_SLICE}" '
        f"meta mark set {FWMARK}\n"
        "  }\n"
        "}\n"
    )


def route_script() -> str:
    """Generate AdGuard VPN CLI SCRIPT-mode hook for selected-app traffic.

    The hook receives the active TUN interface as $1.  Routes are isolated in
    a dedicated table; the normal main table and other nftables tables are not
    flushed or rewritten.
    """
    return f'''#!/bin/sh
set -eu
IFACE="${{1:-}}"
case "$IFACE" in
  ""|*[!A-Za-z0-9_.:-]*) echo "Invalid TUN interface argument" >&2; exit 2 ;;
esac
[ -d "/sys/class/net/$IFACE" ] || {{ echo "TUN interface not found: $IFACE" >&2; exit 2; }}
ip route replace default dev "$IFACE" table {ROUTE_TABLE}
ip -6 route replace default dev "$IFACE" table {ROUTE_TABLE} 2>/dev/null || true
ip rule del priority {RULE_PRIORITY} fwmark {FWMARK} lookup {ROUTE_TABLE} 2>/dev/null || true
ip rule add priority {RULE_PRIORITY} fwmark {FWMARK} lookup {ROUTE_TABLE}
ip -6 rule del priority {RULE_PRIORITY} fwmark {FWMARK} lookup {ROUTE_TABLE} 2>/dev/null || true
ip -6 rule add priority {RULE_PRIORITY} fwmark {FWMARK} lookup {ROUTE_TABLE}
'''


def scope_command(command: Sequence[str], app_id: str) -> list[str]:
    """Return a safe systemd-run command that places an app in our slice."""
    if not command or not command[0]:
        raise ValueError("Пустая команда запуска приложения.")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", app_id).strip("-.")[:40] or "app"
    digest = hashlib.sha256(app_id.encode("utf-8")).hexdigest()[:8]
    unit = f"adguard-vpn-app-{slug}-{digest}.scope"
    return [
        "systemd-run", "--user", "--scope", f"--slice={APP_SLICE}",
        f"--unit={unit}", "--", *[str(part) for part in command],
    ]


def build_plan(interface: str, cgroup_path: str | None = None) -> dict:
    """Return a non-executing preview of the selected-app route setup."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", interface):
        raise ValueError("Недопустимое имя TUN-интерфейса.")
    path = cgroup_path if cgroup_path is not None else current_user_cgroup_path()
    level = cgroup_level_for_slice(path)
    return {
        "interface": interface,
        "cgroup_level": level,
        "nft_table": NFT_TABLE,
        "nft_rules": nft_ruleset(level),
        "route_script": route_script(),
        "route_table": ROUTE_TABLE,
        "fwmark": FWMARK,
        "scope_slice": APP_SLICE,
    }


def check_capabilities() -> tuple[bool, list[str]]:
    """Check prerequisites only; no system state is changed."""
    missing = [name for name in ("systemd-run", "nft", "ip", "adguardvpn-cli") if not shutil.which(name)]
    problems: list[str] = []
    if missing:
        problems.append("Не найдены команды: " + ", ".join(missing))
    try:
        cgroup_path = current_user_cgroup_path()
        if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
            problems.append("Не обнаружен cgroup v2.")
        cgroup_level_for_slice(cgroup_path)
    except RoutingError as exc:
        problems.append(str(exc))
    if os.environ.get("XDG_RUNTIME_DIR") is None:
        problems.append("Не задан XDG_RUNTIME_DIR; пользовательская systemd-сессия недоступна.")
    return not problems, problems


def launch_in_routing_scope(command: Sequence[str], app_id: str) -> subprocess.Popen:
    """Launch an application in the dedicated cgroup slice."""
    ready, problems = check_capabilities()
    if not ready:
        raise RoutingError("; ".join(problems))
    return subprocess.Popen(scope_command(command, app_id), close_fds=True)
