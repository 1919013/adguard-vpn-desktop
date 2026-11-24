"""Narrow, fail-closed root helper for process split-tunnel rules.

The helper accepts only a fixed operation and validated numeric/scope values.
It does not accept arbitrary shell commands, nft snippets, or file paths.
It is not wired into the GUI until packaging and polkit policy are reviewed.
"""
from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

STATE_DIR = Path("/var/lib/adguard-vpn-desktop")
STATE_FILE = STATE_DIR / "split-tunnel.json"
NFT_TABLE = "adguard_vpn_desktop"
NFT_CHAIN = "app_output"
SCOPE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.(?:scope|slice)$")
DEFAULT_MARK = 0xAD61


class HelperError(RuntimeError):
    """A safe split-tunnel operation could not be completed."""


def _run(argv: list[str], *, input_text: str | None = None,
         runner: Callable = subprocess.run) -> tuple[int, str]:
    try:
        result = runner(
            argv, input=input_text, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False, timeout=10,
        )
        return int(result.returncode), (result.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _validate_cgroup_path(cgroup_path: str, scope: str, level: int) -> tuple[str, ...]:
    if not isinstance(cgroup_path, str) or not cgroup_path.startswith("/") or len(cgroup_path) > 4096:
        raise HelperError("Недопустимый абсолютный путь cgroup v2.")
    parts = tuple(part for part in cgroup_path.split("/") if part)
    if (
        len(parts) != level or not parts or parts[0] != "user.slice"
        or parts[-1] != scope or any(part in {".", ".."} for part in parts)
        or not scope.endswith(".slice")
        or len(parts) != 5
        or not (parts[1].startswith("user-") and parts[1].endswith(".slice") and parts[1][5:-6].isdigit())
        or not (parts[2].startswith("user@") and parts[2].endswith(".service") and parts[2][5:-8].isdigit())
        or parts[3] != "app.slice"
        or scope != "app-adguard-vpn.slice"
    ):
        raise HelperError("Путь cgroup v2 должен указывать на общую app-adguard-vpn.slice.")
    if any(not re.fullmatch(r"[A-Za-z0-9_.@:-]+", part) for part in parts):
        raise HelperError("Путь cgroup v2 содержит недопустимые компоненты.")
    return parts


def _cgroup_has_processes(cgroup_path: str, cgroup_root: Path = Path("/sys/fs/cgroup")) -> bool:
    root = Path(cgroup_root)
    target = root.joinpath(*_validate_cgroup_path(
        cgroup_path, Path(cgroup_path).name, len([p for p in cgroup_path.split("/") if p])
    ))
    try:
        if not target.exists():
            return False
        if target.is_symlink() or not target.is_dir():
            raise HelperError("Каталог cgroup scope имеет небезопасный тип.")
        process_files = list(target.rglob("cgroup.procs"))
        if not process_files:
            raise HelperError("Не удалось обнаружить cgroup.procs; правила оставлены для безопасности.")
        for process_file in process_files:
            try:
                if any(line.strip().isdigit() for line in process_file.read_text(encoding="ascii").splitlines()):
                    return True
            except OSError as exc:
                raise HelperError(f"Не удалось проверить активность cgroup: {exc}") from exc
        return False
    except OSError as exc:
        raise HelperError(f"Не удалось проверить каталог cgroup: {exc}") from exc


def _validate(scope: str, level: int, table: int, mark: int, priority: int) -> None:
    if not isinstance(scope, str) or not SCOPE_RE.fullmatch(scope):
        raise HelperError("Недопустимое имя systemd scope.")
    if not isinstance(level, int) or not 1 <= level <= 32:
        raise HelperError("Недопустимый уровень cgroup v2.")
    if not isinstance(table, int) or not 1 <= table <= 2**31 - 1:
        raise HelperError("Недопустимая таблица маршрутизации.")
    if not isinstance(mark, int) or not 0 < mark <= 0xFFFFFFFF:
        raise HelperError("Недопустимая метка пакета.")
    if not isinstance(priority, int) or not 1 <= priority <= 2**31 - 1:
        raise HelperError("Недопустимый приоритет ip rule.")


class SplitTunnelPrivilegedHelper:
    """Apply/remove only helper-owned objects, with rollback on partial failure."""

    def __init__(self, state_file: Path = STATE_FILE, runner: Callable = subprocess.run,
                 euid: Callable[[], int] = os.geteuid,
                 which: Callable[[str], str | None] = shutil.which,
                 cgroup_root: Path = Path("/sys/fs/cgroup")):
        self.state_file = Path(state_file)
        self.runner = runner
        self.euid = euid
        self.which = which
        self.cgroup_root = Path(cgroup_root)

    def _exec(self, argv: list[str], input_text: str | None = None) -> None:
        code, output = _run(argv, input_text=input_text, runner=self.runner)
        if code:
            raise HelperError(output or f"Команда завершилась с кодом {code}: {argv[0]}")

    def _read_state(self) -> dict | None:
        try:
            metadata = self.state_file.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise HelperError(f"Не удалось проверить файл состояния: {exc}") from exc
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise HelperError("Файл состояния должен быть обычным файлом, не ссылкой.")
        if metadata.st_mode & 0o077:
            raise HelperError("Права файла состояния слишком широкие; ожидается доступ только владельцу.")
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HelperError(f"Файл состояния повреждён: {exc}") from exc
        if not isinstance(data, dict) or data.get("owner") != "adguard-vpn-desktop":
            raise HelperError("Файл состояния не принадлежит ADGuard VPN Desktop.")
        return data

    def _write_state(self, data: dict) -> None:
        self.state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            directory = self.state_file.parent.lstat()
        except OSError as exc:
            raise HelperError(f"Не удалось проверить каталог состояния: {exc}") from exc
        if not stat.S_ISDIR(directory.st_mode) or stat.S_ISLNK(directory.st_mode):
            raise HelperError("Каталог состояния не должен быть символической ссылкой.")
        if directory.st_mode & 0o077:
            raise HelperError("Каталог состояния доступен посторонним; требуются права 0700.")
        fd, temporary = tempfile.mkstemp(prefix=".split-tunnel-", dir=self.state_file.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_file)
            os.chmod(self.state_file, 0o600)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def apply(self, *, scope: str, level: int, table: int, cgroup_path: str,
              tunnel_interface: str, dns_servers: list[str] | tuple[str, ...],
              mark: int = DEFAULT_MARK, priority: int = 1061) -> dict:
        if self.euid() != 0:
            raise HelperError("Для изменения nftables и ip rule нужны права root.")
        _validate(scope, level, table, mark, priority)
        _validate_cgroup_path(cgroup_path, scope, level)
        if not isinstance(tunnel_interface, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", tunnel_interface):
            raise HelperError("Недопустимое имя TUN-интерфейса.")
        try:
            dns_servers = sorted({str(ipaddress.ip_address(item)) for item in dns_servers})
        except (TypeError, ValueError) as exc:
            raise HelperError("Список DNS-серверов содержит некорректный IP-адрес.") from exc
        if not dns_servers:
            raise HelperError("Для DNS-защиты требуется хотя бы один проверенный DNS-сервер.")
        existing = self._read_state()
        if existing is not None:
            expected = {
                "scope": scope, "level": level, "table": table, "mark": mark,
                "priority": priority, "cgroup_path": cgroup_path,
                "tunnel_interface": tunnel_interface, "dns_servers": dns_servers,
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise HelperError(
                    "Уже действует другая общая сессия маршрутизации; параметры не совпадают."
                )
            if self.verify_active(
                scope=scope, level=level, table=table, cgroup_path=cgroup_path,
                tunnel_interface=tunnel_interface, dns_servers=dns_servers,
                mark=mark, priority=priority,
            ):
                return {"active": True, "shared": True, "scope": scope,
                        "table": table, "mark": hex(mark), "priority": priority}
            raise HelperError(
                "Состояние общей сессии найдено, но правила не прошли проверку; "
                "существующие правила не изменены."
            )
        # Refuse to adopt or overwrite any pre-existing nft table.
        if not self.which("nft"):
            raise HelperError("Команда nft не установлена или недоступна.")
        code, output = _run(["nft", "list", "tables"], runner=self.runner)
        if code:
            raise HelperError("Не удалось проверить таблицы nftables: " + (output or "ошибка nft"))
        if any(line.strip() == f"table inet {NFT_TABLE}" for line in output.splitlines()):
            raise HelperError("Таблица nftables уже существует; helper не будет её изменять.")
        # Refuse an occupied priority or an existing identical fwmark rule.
        code, rules = _run(["ip", "-j", "rule", "show"], runner=self.runner)
        if code:
            raise HelperError("Не удалось проверить существующие правила ip.")
        try:
            parsed = json.loads(rules or "[]")
        except json.JSONDecodeError as exc:
            raise HelperError("ip rule вернул некорректный JSON.") from exc
        if not isinstance(parsed, list):
            raise HelperError("Неожиданный формат ip rule.")
        for rule in parsed:
            if not isinstance(rule, dict):
                raise HelperError("Неожиданный элемент ip rule.")
            if str(rule.get("priority")) == str(priority):
                raise HelperError("Выбранный приоритет ip rule уже занят.")
            raw = rule.get("fwmark")
            if raw is not None:
                try:
                    value_text, _, mask_text = str(raw).partition("/")
                    value = int(value_text, 0)
                    mask = int(mask_text, 0) if mask_text else 0xFFFFFFFF
                except ValueError:
                    raise HelperError("Не удалось безопасно разобрать существующий fwmark.")
                if (mark & mask) == (value & mask):
                    raise HelperError("Выбранная метка конфликтует с существующим ip rule.")

        nft_lines = [
            f'add table inet {NFT_TABLE} {{ comment "Owned by ADGuard VPN Desktop"; }}',
            f"add chain inet {NFT_TABLE} {NFT_CHAIN} {{ type route hook output priority mangle; policy accept; }}",
            f"add rule inet {NFT_TABLE} {NFT_CHAIN} socket cgroupv2 level {level} {scope} meta mark set {hex(mark)}",
            f"add chain inet {NFT_TABLE} app_guard {{ type filter hook output priority filter; policy accept; }}",
            f'add rule inet {NFT_TABLE} app_guard meta mark {hex(mark)} oifname != "{tunnel_interface}" drop',
        ]
        for server in dns_servers:
            family = "ip6" if ":" in server else "ip"
            for protocol in ("udp", "tcp"):
                nft_lines.insert(
                    3,
                    f"add rule inet {NFT_TABLE} {NFT_CHAIN} {family} daddr {server} {protocol} dport 53 meta mark set {hex(mark)}"
                )
                nft_lines.append(
                    f'add rule inet {NFT_TABLE} app_guard {family} daddr {server} {protocol} dport 53 oifname != "{tunnel_interface}" drop'
                )
        nft_batch = "\n".join(nft_lines) + "\n"
        ip_add = ["ip", "rule", "add", "priority", str(priority),
                  "fwmark", hex(mark), "lookup", str(table)]
        # Record intent first. If the process is interrupted, remove can still
        # clean only this exact table/rule, never unrelated administrator rules.
        state = {
            "owner": "adguard-vpn-desktop", "scope": scope, "level": level,
            "table": table, "mark": mark, "priority": priority,
            "cgroup_path": cgroup_path,
            "cgroup_path": cgroup_path,
            "tunnel_interface": tunnel_interface, "dns_servers": dns_servers,
            "ip_rule": ip_add, "phase": "intent",
        }
        self._write_state(state)
        try:
            self._exec(["nft", "-f", "-"], nft_batch)
            state["phase"] = "nft-created"
            self._write_state(state)
            self._exec(ip_add)
            state["phase"] = "active"
            self._write_state(state)
        except Exception as exc:
            # A failed command may have changed kernel state before returning
            # an error (or the process may have been interrupted between
            # operations). Reconcile against live state through the same
            # ownership-checked remove path. Never discard the recovery record
            # unless both the policy rule and nftables table are verified gone.
            try:
                self.remove()
            except Exception as cleanup_exc:
                raise HelperError(
                    "Не удалось завершить транзакцию и полностью выполнить откат. "
                    f"Состояние восстановления сохранено в {self.state_file}: {cleanup_exc}"
                ) from exc
            if isinstance(exc, HelperError):
                raise
            raise HelperError(f"Транзакция не выполнена; откат проверен: {exc}") from exc
        return {"active": True, "scope": scope, "table": table, "mark": hex(mark), "priority": priority}


    def verify_active(self, *, scope: str, level: int, table: int, cgroup_path: str,
                      tunnel_interface: str, dns_servers: list[str] | tuple[str, ...],
                      mark: int = DEFAULT_MARK, priority: int = 1061) -> bool:
        """Independently verify the exact live nftables and ip rule objects."""
        if self.euid() != 0:
            raise HelperError("Проверка привилегированных правил выполняется через root helper.")
        _validate(scope, level, table, mark, priority)
        _validate_cgroup_path(cgroup_path, scope, level)
        state = self._read_state()
        try:
            dns_servers = sorted({str(ipaddress.ip_address(item)) for item in dns_servers})
        except (TypeError, ValueError):
            return False
        expected = {
            "scope": scope, "level": level, "table": table,
            "mark": mark, "priority": priority,
            "cgroup_path": cgroup_path,
            "tunnel_interface": tunnel_interface, "dns_servers": dns_servers,
        }
        if state is None or any(state.get(key) != value for key, value in expected.items()):
            return False

        code, nft_text = _run(
            ["nft", "list", "chain", "inet", NFT_TABLE, NFT_CHAIN],
            runner=self.runner,
        )
        if code:
            return False
        compact_output = " ".join(nft_text.split()).replace(f'"{scope}"', scope)
        mark_pattern = rf"0x0*{mark:x}"
        expected_rule = (
            rf"socket cgroupv2 level {level} {re.escape(scope)} "
            rf"meta mark set {mark_pattern}"
        )
        if not re.search(expected_rule, compact_output):
            return False
        for server in dns_servers:
            family = "ip6" if ":" in server else "ip"
            if any(
                not re.search(
                    rf"{family} daddr {re.escape(server)} {protocol} dport 53 meta mark set {mark_pattern}",
                    compact_output,
                )
                for protocol in ("udp", "tcp")
            ):
                return False

        code, guard_text = _run(
            ["nft", "list", "chain", "inet", NFT_TABLE, "app_guard"],
            runner=self.runner,
        )
        if code:
            return False
        compact_guard = " ".join(guard_text.split())
        if not re.search(
            rf'meta mark {mark_pattern} oifname != "{re.escape(tunnel_interface)}" drop',
            compact_guard,
        ):
            return False
        for server in dns_servers:
            family = "ip6" if ":" in server else "ip"
            if any(
                not re.search(
                    rf'{family} daddr {re.escape(server)} {protocol} dport 53 oifname != "{re.escape(tunnel_interface)}" drop',
                    compact_guard,
                )
                for protocol in ("udp", "tcp")
            ):
                return False

        code, rules_text = _run(["ip", "-j", "rule", "show"], runner=self.runner)
        if code:
            return False
        try:
            rules = json.loads(rules_text or "[]")
        except json.JSONDecodeError:
            return False
        if not isinstance(rules, list):
            return False
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            try:
                raw_mark = str(rule.get("fwmark", ""))
                mark_text, _, mask_text = raw_mark.partition("/")
                rule_mark = int(mark_text, 0)
                rule_mask = int(mask_text, 0) if mask_text else 0xFFFFFFFF
                rule_table = str(rule.get("table", rule.get("lookup", "")))
                if (
                    str(rule.get("priority", "")) == str(priority)
                    and rule_mark == mark
                    and rule_mask == 0xFFFFFFFF
                    and rule_table == str(table)
                ):
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def remove(self) -> dict:
        if self.euid() != 0:
            raise HelperError("Для изменения nftables и ip rule нужны права root.")
        state = self._read_state()
        if state is None:
            return {"active": False, "removed": False}
        # Reconstruct commands from validated stored values; never execute a
        # command array read from disk.
        _validate(state.get("scope"), state.get("level"), state.get("table"),
                  state.get("mark"), state.get("priority"))
        cgroup_path = state.get("cgroup_path")
        _validate_cgroup_path(cgroup_path, state["scope"], state["level"])
        if _cgroup_has_processes(cgroup_path, self.cgroup_root):
            return {
                "active": True, "removed": False, "deferred": True,
                "reason": "Общая cgroup ещё содержит защищённые процессы.",
            }
        ip_delete = ["ip", "rule", "del", "priority", str(state["priority"]),
                     "fwmark", hex(state["mark"]), "lookup", str(state["table"])]
        # Inspect policy rules first. Never discard state while an owned rule
        # may remain installed: that would make a later cleanup ambiguous.
        code, rules_text = _run(["ip", "-j", "rule", "show"], runner=self.runner)
        if code:
            raise HelperError("Не удалось проверить ip rule перед удалением: " + (rules_text or "ошибка ip"))
        try:
            rules = json.loads(rules_text or "[]")
        except json.JSONDecodeError as exc:
            raise HelperError("ip rule вернул некорректный JSON при удалении.") from exc
        if not isinstance(rules, list) or any(not isinstance(item, dict) for item in rules):
            raise HelperError("Неожиданный формат ip rule при удалении.")

        def is_our_rule(rule: dict) -> bool:
            try:
                raw_mark = str(rule.get("fwmark", ""))
                mark_text, _, mask_text = raw_mark.partition("/")
                parsed_mark = int(mark_text, 0)
                parsed_mask = int(mask_text, 0) if mask_text else 0xFFFFFFFF
                table_value = str(rule.get("table", rule.get("lookup", "")))
                return (
                    str(rule.get("priority", "")) == str(state["priority"])
                    and parsed_mark == state["mark"]
                    and parsed_mask == 0xFFFFFFFF
                    and table_value == str(state["table"])
                )
            except (TypeError, ValueError):
                return False

        if any(is_our_rule(rule) for rule in rules):
            self._exec(ip_delete)
            code, verify_text = _run(["ip", "-j", "rule", "show"], runner=self.runner)
            if code:
                raise HelperError("Не удалось проверить удаление ip rule: " + (verify_text or "ошибка ip"))
            try:
                remaining = json.loads(verify_text or "[]")
            except json.JSONDecodeError as exc:
                raise HelperError("ip rule вернул некорректный JSON после удаления.") from exc
            if not isinstance(remaining, list) or any(not isinstance(item, dict) for item in remaining):
                raise HelperError("Неожиданный формат ip rule после удаления.")
            if any(is_our_rule(rule) for rule in remaining):
                raise HelperError("Правило ip rule осталось в системе; состояние сохранено для повторной очистки.")

        # The table name is exclusively owned because apply refuses preexistence.
        code, table_text = _run(["nft", "list", "table", "inet", NFT_TABLE], runner=self.runner)
        if code == 0:
            if 'comment "Owned by ADGuard VPN Desktop"' not in table_text:
                raise HelperError("Таблица существует, но маркер владения отсутствует; удаление отменено.")
            self._exec(["nft", "delete", "table", "inet", NFT_TABLE])
        elif "No such file" not in table_text and "does not exist" not in table_text:
            raise HelperError("Не удалось проверить таблицу nftables перед удалением: " + (table_text or "ошибка nft"))
        self.state_file.unlink(missing_ok=True)
        return {"active": False, "removed": True}


def main(argv=None) -> int:
    """Command-line entry point used only by the fixed pkexec helper."""
    parser = argparse.ArgumentParser(prog="adguard-vpn-desktop-helper")
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("apply", "verify"):
        command = sub.add_parser(operation)
        command.add_argument("--scope", required=True)
        command.add_argument("--level", required=True, type=int)
        command.add_argument("--table", required=True, type=int)
        command.add_argument("--cgroup", required=True)
        command.add_argument("--tunnel", required=True)
        command.add_argument("--dns-server", action="append", required=True)
        command.add_argument("--priority", type=int, default=1061)
    sub.add_parser("remove")
    args = parser.parse_args(argv)
    helper = SplitTunnelPrivilegedHelper()
    try:
        # Serialize root-side apply/verify/remove transactions. This closes
        # the race where the last app exits while another gated app is joining.
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open("/run/lock/adguard-vpn-desktop-helper.lock", flags, 0o600)
        try:
            metadata = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                or metadata.st_mode & 0o077
            ):
                raise HelperError("Файл блокировки helper имеет небезопасного владельца или права.")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if args.operation in ("apply", "verify"):
                caller_uid = os.environ.get("PKEXEC_UID", "")
                parts = [part for part in args.cgroup.split("/") if part]
                if (
                    not caller_uid.isdigit() or len(parts) != 5
                    or parts[1] != f"user-{caller_uid}.slice"
                    or parts[2] != f"user@{caller_uid}.service"
                ):
                    raise HelperError("Путь cgroup не принадлежит пользователю, запросившему polkit.")
            if args.operation == "apply":
                result = helper.apply(
                    scope=args.scope, level=args.level, table=args.table, cgroup_path=args.cgroup,
                    tunnel_interface=args.tunnel, dns_servers=args.dns_server,
                    priority=args.priority,
                )
            elif args.operation == "verify":
                result = {
                    "ready": helper.verify_active(
                        scope=args.scope, level=args.level, table=args.table, cgroup_path=args.cgroup,
                        tunnel_interface=args.tunnel, dns_servers=args.dns_server,
                        priority=args.priority,
                    )
                }
            else:
                result = helper.remove()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        finally:
            os.close(lock_fd)
    except (HelperError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
