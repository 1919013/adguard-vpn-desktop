"""Narrow, fail-closed root helper for process split-tunnel rules.

The helper accepts only a fixed operation and validated numeric/scope values.
It does not accept arbitrary shell commands, nft snippets, or file paths.
It is not wired into the GUI until packaging and polkit policy are reviewed.
"""
from __future__ import annotations

import argparse
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
SCOPE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.scope$")
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
                 which: Callable[[str], str | None] = shutil.which):
        self.state_file = Path(state_file)
        self.runner = runner
        self.euid = euid
        self.which = which

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

    def apply(self, *, scope: str, level: int, table: int,
              mark: int = DEFAULT_MARK, priority: int = 1061) -> dict:
        if self.euid() != 0:
            raise HelperError("Для изменения nftables и ip rule нужны права root.")
        _validate(scope, level, table, mark, priority)
        if self._read_state() is not None:
            raise HelperError("Уже существует состояние раздельной маршрутизации; сначала выполните remove.")
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

        nft_batch = (
            f'add table inet {NFT_TABLE} {{ comment "Owned by ADGuard VPN Desktop"; }}\n'
            f"add chain inet {NFT_TABLE} {NFT_CHAIN} "
            "{ type route hook output priority mangle; policy accept; }\n"
            f"add rule inet {NFT_TABLE} {NFT_CHAIN} "
            f"socket cgroupv2 level {level} {scope} meta mark set {hex(mark)}\n"
        )
        ip_add = ["ip", "rule", "add", "priority", str(priority),
                  "fwmark", hex(mark), "lookup", str(table)]
        # Record intent first. If the process is interrupted, remove can still
        # clean only this exact table/rule, never unrelated administrator rules.
        state = {
            "owner": "adguard-vpn-desktop", "scope": scope, "level": level,
            "table": table, "mark": mark, "priority": priority,
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


    def verify_active(self, *, scope: str, level: int, table: int,
                      mark: int = DEFAULT_MARK, priority: int = 1061) -> bool:
        """Independently verify the exact live nftables and ip rule objects."""
        if self.euid() != 0:
            raise HelperError("Проверка привилегированных правил выполняется через root helper.")
        _validate(scope, level, table, mark, priority)
        state = self._read_state()
        expected = {
            "scope": scope, "level": level, "table": table,
            "mark": mark, "priority": priority,
        }
        if state is None or any(state.get(key) != value for key, value in expected.items()):
            return False

        code, nft_text = _run(
            ["nft", "list", "chain", "inet", NFT_TABLE, NFT_CHAIN],
            runner=self.runner,
        )
        if code:
            return False
        expected_rule = (
            f"socket cgroupv2 level {level} {scope} "
            f"meta mark set {hex(mark)}"
        )
        if expected_rule not in " ".join(nft_text.split()):
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
    sub.add_parser("remove")
    args = parser.parse_args(argv)
    helper = SplitTunnelPrivilegedHelper()
    try:
        if args.operation == "apply":
            result = helper.apply(
                scope=args.scope, level=args.level, table=args.table
            )
        elif args.operation == "verify":
            result = {
                "ready": helper.verify_active(
                    scope=args.scope, level=args.level, table=args.table
                )
            }
        else:
            result = helper.remove()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except HelperError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
