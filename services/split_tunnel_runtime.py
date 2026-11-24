"""Orchestrate fail-closed application launch, VPN monitoring and DNS checks."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from core.commands import run_cli
from services.dns_leak_guard import DNSLeakGuard
from services.polkit_split_tunnel import PolkitSplitTunnelClient
from services.routing_inspector import RoutingInspector
from services.split_tunnel_launch_gate import SplitTunnelLaunchGate, LaunchGateError
from services.split_tunnel_planner import build_split_tunnel_plan
from services.vpn_status_watcher import VPNStatusWatcher


class SplitTunnelRuntimeError(RuntimeError):
    pass


def read_cli_split_tunnel_config(runner=run_cli) -> dict:
    code, output = runner(["config", "show"], timeout=12)
    if code:
        raise SplitTunnelRuntimeError(
            "Не удалось прочитать конфигурацию AdGuard VPN CLI: " + (output or "ошибка CLI")
        )
    def capture(pattern):
        match = re.search(pattern, output or "", re.IGNORECASE | re.MULTILINE)
        return match.group(1).upper() if match else None

    vpn_mode = capture(r"^\s*(?:VPN\s+)?Mode\s*[:=]\s*(TUN|SOCKS)\b")
    routing_mode = capture(r"^\s*(?:VPN\s+)?(?:(?:TUN|tunnel)\s+)?Routing\s+Mode\s*[:=]\s*(SCRIPT|AUTO|NONE)\b")
    dns_match = re.search(
        r"^\s*Change\s+system\s+DNS\s*[:=]\s*(on|off|yes|no|true|false)\b",
        output or "", re.IGNORECASE | re.MULTILINE,
    )
    dns_enabled = bool(dns_match and dns_match.group(1).casefold() in ("on", "yes", "true"))
    if vpn_mode != "TUN" or routing_mode != "SCRIPT" or not dns_enabled:
        raise SplitTunnelRuntimeError(
            "Раздельный туннель заблокирован. Требуются режим TUN, режим маршрутизации SCRIPT "
            "и Change system DNS: on. Текущая конфигурация не распознана или не соответствует требованиям."
        )
    return {"vpn_mode": vpn_mode, "routing_mode": routing_mode, "change_system_dns": dns_enabled}


class SplitTunnelRuntime:
    """Run a selected app only while VPN, routes and DNS pass preflight."""

    def __init__(self, *, inspector=None, dns_guard=None, watcher=None,
                 helper=None, gate=None, runner=run_cli):
        self.runner = runner
        self.inspector = inspector or RoutingInspector()
        self.dns_guard = dns_guard or DNSLeakGuard()
        self.watcher = watcher or VPNStatusWatcher(runner=runner)
        self.helper = helper or PolkitSplitTunnelClient()
        self.gate = gate or SplitTunnelLaunchGate()

    @staticmethod
    def _nft_table_is_absent() -> bool:
        nft = shutil.which("nft")
        if not nft:
            return False
        try:
            result = subprocess.run(
                [nft, "list", "tables"], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=8, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and not any(
            line.strip() == "table inet adguard_vpn_desktop"
            for line in result.stdout.splitlines()
        )

    @staticmethod
    def _already_running(application) -> bool:
        executable = Path(application.exec_argv[0]).name
        flatpak_id = application.desktop_id.removesuffix(".desktop")
        proc = Path("/proc")
        try:
            entries = list(proc.iterdir())
        except OSError:
            return True
        for entry in entries:
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
                argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
                comm = (entry / "comm").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if application.flatpak:
                name_tokens = [
                    token.casefold() for token in re.findall(r"[A-Za-z0-9]{4,}", application.name)
                ]
                if flatpak_id in argv or any(token in comm.casefold() for token in name_tokens):
                    return True
            if not application.flatpak and (comm == executable or (argv and Path(argv[0]).name == executable)):
                return True
        return False

    def launch(self, application) -> int:
        if self._already_running(application):
            raise SplitTunnelRuntimeError(
                "Обнаружен уже запущенный экземпляр приложения. Сначала полностью закрой его, "
                "иначе desktop/D-Bus activation может передать запрос процессу вне VPN-группы."
            )
        if application.dbus_activatable:
            raise SplitTunnelRuntimeError(
                "Приложение использует D-Bus activation; запуск в отдельной cgroup пока запрещён."
            )
        config = read_cli_split_tunnel_config(self.runner)
        snapshot = self.inspector.inspect()
        if not snapshot.connected or not snapshot.tunnel_interface:
            raise SplitTunnelRuntimeError("AdGuard VPN CLI не подтвердил активный TUN-туннель.")
        dns = self.dns_guard.inspect(snapshot.tunnel_interface)
        if not dns["ready"]:
            raise SplitTunnelRuntimeError(
                "DNS-защита не подтверждена; приложение не будет запущено:\n- "
                + "\n- ".join(dns["reasons"])
            )
        table_absent = self._nft_table_is_absent()
        if not table_absent:
            # Recover only state owned by this helper. If ownership cannot be
            # proven, leave the table untouched and refuse to launch.
            try:
                self.helper.remove()
            except Exception as exc:
                raise SplitTunnelRuntimeError(
                    "Не удалось безопасно очистить оставшиеся правила ADGuard VPN Desktop: " + str(exc)
                ) from exc
            table_absent = self._nft_table_is_absent()
        if not table_absent:
            raise SplitTunnelRuntimeError(
                "Нельзя безопасно создать правила: таблица nftables уже существует "
                "или nft недоступен; существующая таблица не была изменена."
            )

        watch = self.watcher.start(snapshot.tunnel_interface)
        if watch.cancel_event.is_set():
            watch.stop()
            raise SplitTunnelRuntimeError("VPN отключён или изменил TUN до запуска приложения.")

        policy = {}
        try:
            def apply_rules(cgroup_path: str):
                parts = [part for part in cgroup_path.split("/") if part]
                if not parts:
                    raise SplitTunnelRuntimeError("Пустой путь cgroup v2.")
                plan = build_split_tunnel_plan(
                    snapshot, cgroup_path,
                    routing_mode=config["routing_mode"],
                    dns_policy_ready=dns["ready"],
                    nft_table_absent=table_absent,
                )
                if not plan.ready or plan.route_table is None or plan.rule_priority is None:
                    raise SplitTunnelRuntimeError(
                        "План маршрутизации не прошёл проверку:\n- " + "\n- ".join(plan.reasons)
                    )
                scope = parts[-1]
                level = len(parts)
                policy.update({
                    "scope": scope, "level": level,
                    "table": plan.route_table, "priority": plan.rule_priority,
                })
                policy["apply_attempted"] = True
                self.helper.apply(
                    scope=scope, level=level, table=plan.route_table,
                    tunnel=snapshot.tunnel_interface,
                    dns_servers=tuple(dns["servers"]),
                    priority=plan.rule_priority,
                )

            def verify_rules(_cgroup_path: str) -> bool:
                return self.helper.verify(
                    scope=policy["scope"], level=policy["level"],
                    table=policy["table"], tunnel=snapshot.tunnel_interface,
                    dns_servers=tuple(dns["servers"]),
                    priority=policy["priority"],
                )

            def remove_rules():
                if policy.get("apply_attempted"):
                    self.helper.remove()

            return self.gate.run(
                application.exec_argv, application.desktop_id,
                apply_rules=apply_rules, verify_rules=verify_rules,
                remove_rules=remove_rules, cancel_event=watch.cancel_event,
            )
        except LaunchGateError as exc:
            raise SplitTunnelRuntimeError(str(exc)) from exc
        finally:
            watch.stop()
