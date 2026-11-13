"""Per-application TUN routing using systemd cgroups, nftables and policy routing.

All changes are confined to this application's private nftables table, route
table and rule priorities. The AdGuard route hook owns setup/cleanup of kernel
state; the GUI only installs/restores the hook and launches apps in a scope.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

NFT_TABLE = "adguard_vpn_desktop"
NFT_CHAIN = "app_output"
APP_SLICE = "adguard-vpn-apps.slice"
VPN_MARK = "0xAD61"
DIRECT_MARK = "0xAD62"
ROUTE_TABLE = "51861"
VPN_RULE_PRIORITY = "10610"
DIRECT_RULE_PRIORITY = "10609"
VALID_MODES = {"selected", "all_except_selected"}


class RoutingError(RuntimeError):
    """Raised when per-app TUN routing cannot be configured safely."""


def _uid() -> int:
    return os.getuid()


def user_manager_component(uid: int | None = None) -> str:
    return f"user@{_uid() if uid is None else int(uid)}.service"


def cgroup_level_for_component(cgroup_path: str, component: str) -> int:
    parts = [part for part in cgroup_path.strip("/").split("/") if part]
    if component in parts:
        return parts.index(component) + 1
    raise RoutingError(f"Компонент cgroup не найден: {component}")


def cgroup_level_for_slice(cgroup_path: str, slice_name: str = APP_SLICE) -> int:
    """Find the level of our slice, or its future child level under user@UID."""
    parts = [part for part in cgroup_path.strip("/").split("/") if part]
    if slice_name in parts:
        return parts.index(slice_name) + 1
    manager = user_manager_component()
    if manager not in parts:
        raise RoutingError("Не найден cgroup пользовательского systemd-менеджера.")
    # The app slice is a direct child of user@UID.service.
    return parts.index(manager) + 2


def current_user_cgroup_path() -> str:
    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
            if line.startswith("0::"):
                return line[3:]
    except OSError as exc:
        raise RoutingError(f"Не удалось прочитать cgroup v2: {exc}") from exc
    raise RoutingError("Не обнаружена единая иерархия cgroup v2.")


def nft_ruleset(mode: str, app_level: int, manager_level: int | None = None) -> str:
    if mode not in VALID_MODES:
        raise ValueError("Неизвестный режим раздельного туннелирования.")
    if not 1 <= app_level <= 32:
        raise ValueError("Недопустимый уровень cgroup приложений.")
    manager_level = manager_level or app_level - 1
    if not 1 <= manager_level < app_level <= 32:
        raise ValueError("Некорректная иерархия cgroup.")
    manager = user_manager_component()
    rules = []
    if mode == "selected":
        rules.append(
            f'    socket cgroupv2 level {app_level} "{APP_SLICE}" meta mark set {VPN_MARK}'
        )
    else:
        # Mark all processes in this user's systemd session for VPN, then
        # override selected app scopes to use the physical/main routing table.
        rules.extend([
            f'    socket cgroupv2 level {manager_level} "{manager}" meta mark set {VPN_MARK}',
            f'    socket cgroupv2 level {app_level} "{APP_SLICE}" meta mark set {DIRECT_MARK}',
        ])
    return (
        f"table inet {NFT_TABLE} {{\n"
        f"  chain {NFT_CHAIN} {{\n"
        "    type route hook output priority mangle; policy accept;\n"
        + "\n".join(rules) + "\n"
        "  }\n"
        "}\n"
    )


def route_script(mode: str = "selected", app_level: int = 4,
                 manager_level: int = 3) -> str:
    """AdGuard VPN CLI SCRIPT hook; its first argument is the TUN interface."""
    if mode not in VALID_MODES:
        raise ValueError("Неизвестный режим раздельного туннелирования.")
    rules = nft_ruleset(mode, app_level, manager_level)
    # Interface-down is handled by the same hook when the interface no longer
    # exists, and by the explicit GUI disconnect path.
    return f'''#!/bin/sh
set -eu
TABLE="{ROUTE_TABLE}"
NFT_TABLE="{NFT_TABLE}"
IFACE="${{1:-}}"
cleanup() {{
  ip rule del priority {VPN_RULE_PRIORITY} fwmark {VPN_MARK} lookup "$TABLE" 2>/dev/null || true
  ip -6 rule del priority {VPN_RULE_PRIORITY} fwmark {VPN_MARK} lookup "$TABLE" 2>/dev/null || true
  ip rule del priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main 2>/dev/null || true
  ip -6 rule del priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main 2>/dev/null || true
  ip route flush table "$TABLE" 2>/dev/null || true
  ip -6 route flush table "$TABLE" 2>/dev/null || true
  nft delete table inet "$NFT_TABLE" 2>/dev/null || true
}}
if [ "${{1:-}}" = "--cleanup" ] || [ -z "$IFACE" ] || [ ! -d "/sys/class/net/$IFACE" ]; then
  cleanup
  exit 0
fi
case "$IFACE" in
  *[!A-Za-z0-9_.:-]*) echo "Invalid TUN interface argument" >&2; exit 2 ;;
esac
# Build the tunnel table first; do not change the main/default route.
ip route replace default dev "$IFACE" table "$TABLE"
ip -6 route replace default dev "$IFACE" table "$TABLE"
ip rule del priority {VPN_RULE_PRIORITY} fwmark {VPN_MARK} lookup "$TABLE" 2>/dev/null || true
ip rule add priority {VPN_RULE_PRIORITY} fwmark {VPN_MARK} lookup "$TABLE"
ip -6 rule del priority {VPN_RULE_PRIORITY} fwmark {VPN_MARK} lookup "$TABLE" 2>/dev/null || true
ip -6 rule add priority {VPN_RULE_PRIORITY} fwmark {VPN_MARK} lookup "$TABLE"
if [ "{mode}" = "all_except_selected" ]; then
  ip rule del priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main 2>/dev/null || true
  ip rule add priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main
  ip -6 rule del priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main 2>/dev/null || true
  ip -6 rule add priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main
else
  ip rule del priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main 2>/dev/null || true
  ip -6 rule del priority {DIRECT_RULE_PRIORITY} fwmark {DIRECT_MARK} lookup main 2>/dev/null || true
fi
nft delete table inet "$NFT_TABLE" 2>/dev/null || true
nft -f - <<'NFT_EOF'
{rules.rstrip()}
NFT_EOF
'''


def scope_command(command: Sequence[str], app_id: str) -> list[str]:
    if not command or not command[0]:
        raise ValueError("Пустая команда запуска приложения.")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", app_id).strip("-.")[:40] or "app"
    digest = hashlib.sha256(app_id.encode("utf-8")).hexdigest()[:8]
    unit = f"adguard-vpn-app-{slug}-{digest}.scope"
    return [
        "systemd-run", "--user", "--scope", f"--slice={APP_SLICE}",
        f"--unit={unit}", "--", *[str(part) for part in command],
    ]


def route_script_path() -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return data / "adguardvpn-cli" / "setup_routes.sh"


def state_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "adguard-vpn-desktop" / "app-routing-backup.json"


def _run(args: Sequence[str], timeout: int = 25) -> tuple[int, str]:
    try:
        result = subprocess.run(list(args), text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _config_value(output: str, names: Sequence[str]) -> str | None:
    for line in output.splitlines():
        for name in names:
            match = re.match(rf"\s*{re.escape(name)}\s*[:=]\s*(.*?)\s*$", line, re.I)
            if match:
                return match.group(1).strip()
    return None


def configure(mode: str, cgroup_path: str | None = None) -> tuple[int, str]:
    """Install a reversible route hook and configure the CLI for TUN/SCRIPT."""
    if mode not in VALID_MODES:
        return 2, "Выберите один из двух режимов раздельного туннелирования."
    missing = [name for name in ("adguardvpn-cli", "systemd-run", "nft", "ip") if not shutil.which(name)]
    if missing:
        return 2, "Не найдены системные компоненты: " + ", ".join(missing)
    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        return 2, "Для маршрутизации приложений требуется cgroup v2."
    try:
        path = cgroup_path if cgroup_path is not None else current_user_cgroup_path()
        manager_level = cgroup_level_for_component(path, user_manager_component())
        app_level = cgroup_level_for_slice(path)
        script = route_script(mode, app_level, manager_level)
    except (RoutingError, ValueError) as exc:
        return 2, str(exc)

    state = state_path()
    hook = route_script_path()
    if state.exists():
        return 2, "Раздельное туннелирование уже настроено. Сначала отключите его штатной кнопкой."
    code, config = _run(["adguardvpn-cli", "config", "show"])
    if code:
        return code, config or "Не удалось прочитать конфигурацию AdGuard VPN CLI."
    old_vpn_mode = _config_value(config, ("Mode", "VPN mode")) or "UNKNOWN"
    old_route_mode = _config_value(config, ("TUN routing mode", "Tunnel routing mode")) or "UNKNOWN"
    try:
        hook.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if hook.is_symlink():
            return 2, "Файл route script является символической ссылкой; настройка отменена."
        if not hook.exists():
            code, output = _run(["adguardvpn-cli", "config", "create-route-script"])
            if code or not hook.is_file():
                return code or 2, output or (
                    "AdGuard VPN CLI не создал ожидаемый route script: " + str(hook)
                )
        if hook.is_symlink():
            return 2, "Файл route script является символической ссылкой; настройка отменена."
        previous_script = hook.read_text(encoding="utf-8") if hook.exists() else None
        payload = {
            "version": 1, "mode": mode, "hook": str(hook),
            "previous_script": previous_script,
            "previous_vpn_mode": old_vpn_mode,
            "previous_route_mode": old_route_mode,
        }
        # Save rollback data before touching CLI settings or the route hook.
        state.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(state, 0o600)
        hook.write_text(script, encoding="utf-8")
        os.chmod(hook, 0o700)
        code, output = _run(["adguardvpn-cli", "config", "set-mode", "TUN"])
        if code:
            raise RoutingError(output or "Не удалось включить режим TUN.")
        code, output = _run(["adguardvpn-cli", "config", "set-tun-routing-mode", "SCRIPT"])
        if code:
            raise RoutingError(output or "Не удалось включить режим SCRIPT.")
    except Exception as exc:
        # Best-effort rollback of the user's script and CLI settings.
        try:
            if "previous_script" in locals():
                if previous_script is None:
                    hook.unlink(missing_ok=True)
                else:
                    hook.write_text(previous_script, encoding="utf-8")
                    os.chmod(hook, 0o700)
            if old_vpn_mode != "UNKNOWN":
                _run(["adguardvpn-cli", "config", "set-mode", old_vpn_mode])
            if old_route_mode != "UNKNOWN":
                _run(["adguardvpn-cli", "config", "set-tun-routing-mode", old_route_mode])
            state.unlink(missing_ok=True)
        except OSError:
            pass
        return 1, f"Настройка отменена; выполнен откат, где это удалось: {exc}"
    return 0, (
        "Настроен режим раздельного туннелирования TUN/SCRIPT. "
        "Переподключите VPN, чтобы AdGuard VPN CLI вызвал route script. "
        "Приложения запускайте через созданные VPN-ярлыки."
    )


def reconfigure(mode: str, cgroup_path: str | None = None) -> tuple[int, str]:
    """Change the active policy while retaining the original rollback snapshot."""
    if mode not in VALID_MODES:
        return 2, "Неизвестный режим раздельного туннелирования."
    state = state_path()
    if not state.is_file() or state.is_symlink():
        return configure(mode, cgroup_path)
    try:
        path = cgroup_path if cgroup_path is not None else current_user_cgroup_path()
        manager_level = cgroup_level_for_component(path, user_manager_component())
        app_level = cgroup_level_for_slice(path)
        script = route_script(mode, app_level, manager_level)
        payload = json.loads(state.read_text(encoding="utf-8"))
        hook = Path(payload["hook"])
        if hook != route_script_path() or hook.is_symlink():
            raise RoutingError("Путь route script не совпадает с сохранённым безопасным путём.")
        hook.write_text(script, encoding="utf-8")
        os.chmod(hook, 0o700)
        payload["mode"] = mode
        state.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(state, 0o600)
        return 0, "Режим изменён. Переподключите VPN для применения новой политики."
    except (OSError, ValueError, KeyError, TypeError, RoutingError) as exc:
        return 1, f"Не удалось изменить режим: {exc}"


def cleanup_kernel_state() -> tuple[int, str]:
    """Remove only the dedicated nftables table, rules and route table."""
    hook = route_script_path()
    if not hook.is_file() or hook.is_symlink():
        return 0, "Файл маршрутизации не найден; дополнительных правил не удалено."
    return _run(["pkexec", str(hook), "--cleanup"], timeout=30)


def disable() -> tuple[int, str]:
    """Remove owned kernel state and restore the previous route script/settings."""
    state = state_path()
    if not state.is_file() or state.is_symlink():
        return 2, "Нет сохранённой конфигурации для безопасного восстановления."
    try:
        payload = json.loads(state.read_text(encoding="utf-8"))
        hook = Path(payload["hook"])
        if hook != route_script_path() or hook.is_symlink():
            raise RoutingError("Путь route script не совпадает с сохранённым безопасным путём.")
        code, output = cleanup_kernel_state()
        if code:
            return code, output or "Не удалось очистить правила маршрутизации (pkexec)."
        previous = payload.get("previous_script")
        if previous is None:
            hook.unlink(missing_ok=True)
        else:
            hook.write_text(previous, encoding="utf-8")
            os.chmod(hook, 0o700)
        route_mode = payload.get("previous_route_mode")
        vpn_mode = payload.get("previous_vpn_mode")
        if route_mode and route_mode != "UNKNOWN":
            code, output = _run(["adguardvpn-cli", "config", "set-tun-routing-mode", route_mode])
            if code:
                return code, "Скрипт восстановлен, но не удалось вернуть режим маршрутизации CLI: " + output
        if vpn_mode and vpn_mode != "UNKNOWN":
            code, output = _run(["adguardvpn-cli", "config", "set-mode", vpn_mode])
            if code:
                return code, "Маршрутизация восстановлена, но не удалось вернуть режим VPN CLI: " + output
        state.unlink(missing_ok=True)
        return 0, "Раздельное туннелирование отключено; собственные маршруты и прежний route script восстановлены."
    except (OSError, ValueError, KeyError, TypeError, RoutingError) as exc:
        return 1, f"Не удалось безопасно восстановить настройки: {exc}"


def check_capabilities() -> tuple[bool, list[str]]:
    missing = [name for name in ("systemd-run", "nft", "ip", "adguardvpn-cli", "pkexec") if not shutil.which(name)]
    problems = []
    if missing:
        problems.append("Не найдены команды: " + ", ".join(missing))
    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        problems.append("Требуется cgroup v2.")
    try:
        path = current_user_cgroup_path()
        cgroup_level_for_component(path, user_manager_component())
        cgroup_level_for_slice(path)
    except RoutingError as exc:
        problems.append(str(exc))
    if not os.environ.get("XDG_RUNTIME_DIR"):
        problems.append("Не задан XDG_RUNTIME_DIR; пользовательская systemd-сессия недоступна.")
    return not problems, problems
