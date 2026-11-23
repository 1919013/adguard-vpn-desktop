"""Process-aware split-tunneling primitives for Linux.

This module is intentionally non-mutating. It discovers cgroup-v2 support,
builds launch commands that place an application (and its descendants) in a
dedicated systemd user scope, and describes the policy-routing operations
needed by a future privileged helper. It never edits routes or nftables.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


CGROUP_ROOT = Path("/sys/fs/cgroup")
DEFAULT_MARK = 0xAD61
DEFAULT_TABLE = 51820
DEFAULT_RULE_PRIORITY = 1061
_UNIT_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


class SplitTunnelError(RuntimeError):
    """Raised when a process cannot safely be placed in a routing scope."""


@dataclass(frozen=True)
class LinuxCapabilities:
    cgroup_v2: bool
    systemd_user: bool
    nft: bool
    iproute2: bool
    adguard_cli: bool
    reasons: tuple[str, ...]


def detect_capabilities(
    cgroup_root: Path = CGROUP_ROOT,
    which=shutil.which,
    environ=None,
) -> LinuxCapabilities:
    """Inspect prerequisites without changing the host."""
    env = os.environ if environ is None else environ
    reasons: list[str] = []
    cgroup_v2 = (cgroup_root / "cgroup.controllers").is_file()
    if not cgroup_v2:
        reasons.append("Не обнаружена единая иерархия cgroup v2.")
    systemd_user = bool(env.get("XDG_RUNTIME_DIR")) and bool(which("systemd-run"))
    if not systemd_user:
        reasons.append("Недоступен systemd-run в пользовательской сессии.")
    nft = bool(which("nft"))
    if not nft:
        reasons.append("Не найдена команда nft.")
    iproute2 = bool(which("ip"))
    if not iproute2:
        reasons.append("Не найдена команда ip из iproute2.")
    adguard_cli = bool(which("adguardvpn-cli"))
    if not adguard_cli:
        reasons.append("Не найдена команда adguardvpn-cli.")
    return LinuxCapabilities(cgroup_v2, systemd_user, nft, iproute2, adguard_cli, tuple(reasons))


def _safe_unit_name(app_id: str) -> str:
    value = _UNIT_SAFE.sub("-", app_id.strip()).strip("-.")
    if not value:
        raise SplitTunnelError("Не удалось сформировать безопасное имя systemd scope.")
    return ("adguard-vpn-" + value.lower())[:55]


def build_scoped_launch_command(
    command: Sequence[str],
    app_id: str,
    *,
    systemd_run: str = "systemd-run",
) -> list[str]:
    """Return argv for launching an app in a dedicated user cgroup scope.

    This works for native commands and Flatpak commands alike: Flatpak and
    application child processes inherit the scope's cgroup membership.
    """
    if isinstance(command, (str, bytes)) or not command:
        raise SplitTunnelError("Команда запуска приложения пуста или задана строкой.")
    if not all(isinstance(part, str) and part for part in command):
        raise SplitTunnelError("Команда запуска содержит пустой или некорректный аргумент.")
    unit = _safe_unit_name(app_id)
    return [
        systemd_run, "--user", "--scope", "--collect",
        "--unit", unit, "--slice", "app.slice", "--",
        *command,
    ]


def read_process_cgroup(pid: int, proc_root: Path = Path("/proc")) -> str:
    """Return a validated cgroup-v2 path for a host PID."""
    if not isinstance(pid, int) or pid <= 0:
        raise SplitTunnelError("PID должен быть положительным целым числом.")
    try:
        lines = (proc_root / str(pid) / "cgroup").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SplitTunnelError(f"Не удалось прочитать cgroup процесса {pid}: {exc}") from exc
    for line in lines:
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            path = fields[2]
            if not path.startswith("/") or ".." in Path(path).parts:
                break
            return path
    raise SplitTunnelError(f"Для процесса {pid} не найден путь cgroup v2.")


def cgroup_v2_id(cgroup_path: str, cgroup_root: Path = CGROUP_ROOT) -> int:
    """Get the kernel cgroup ID (directory inode) for nft 'meta cgroup'."""
    relative = Path(cgroup_path.lstrip("/"))
    if ".." in relative.parts:
        raise SplitTunnelError("Недопустимый путь cgroup.")
    root = cgroup_root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise SplitTunnelError("Путь cgroup выходит за пределы cgroup v2.")
    try:
        if not target.is_dir():
            raise SplitTunnelError("Каталог cgroup процесса не существует.")
        return target.stat().st_ino
    except OSError as exc:
        raise SplitTunnelError(f"Не удалось получить ID cgroup: {exc}") from exc


def nft_cgroup_mark_rule(cgroup_id: int, mark: int = DEFAULT_MARK) -> list[str]:
    """Build an nft command that marks packets created by one app cgroup."""
    if not isinstance(cgroup_id, int) or cgroup_id <= 0:
        raise SplitTunnelError("Некорректный ID cgroup.")
    if not isinstance(mark, int) or not 0 < mark <= 0xFFFFFFFF:
        raise SplitTunnelError("Некорректная метка пакета.")
    return [
        "nft", "add", "rule", "inet", "adguard_vpn_desktop", "app_output",
        "meta", "cgroup", str(cgroup_id), "meta", "mark", "set", hex(mark),
    ]


def policy_rule_command(
    mark: int = DEFAULT_MARK,
    table: int = DEFAULT_TABLE,
    priority: int = DEFAULT_RULE_PRIORITY,
) -> list[str]:
    """Build an iproute2 rule mapping the app mark to the VPN route table."""
    if not 0 < mark <= 0xFFFFFFFF:
        raise SplitTunnelError("Некорректная метка пакета.")
    if not 1 <= table <= 2**31 - 1:
        raise SplitTunnelError("Некорректный номер таблицы маршрутизации.")
    if not 1 <= priority <= 2**31 - 1:
        raise SplitTunnelError("Некорректный приоритет правила.")
    return [
        "ip", "rule", "add", "priority", str(priority),
        "fwmark", hex(mark), "lookup", str(table),
    ]


def is_flatpak_command(command: Sequence[str]) -> bool:
    """Identify Flatpak launch argv without relying on the desktop display name."""
    return bool(command) and Path(command[0]).name == "flatpak" and len(command) >= 2 and command[1] == "run"


def run_read_only(command: Sequence[str], timeout: int = 5) -> tuple[int, str]:
    """Run an inspection command without a shell; do not use for mutations."""
    try:
        result = subprocess.run(
            list(command), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
