"""Narrow, fail-closed root helper for process split-tunnel rules.

The helper accepts only a fixed operation and validated numeric/scope values.
It does not accept arbitrary shell commands, nft snippets, or file paths.
It is not wired into the GUI until packaging and polkit policy are reviewed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
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
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise HelperError(f"Файл состояния повреждён: {exc}") from exc
        if not isinstance(data, dict) or data.get("owner") != "adguard-vpn-desktop":
            raise HelperError("Файл состояния не принадлежит ADGuard VPN Desktop.")
        return data

    def _write_state(self, data: dict) -> None:
        self.state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
        ip_delete = ["ip", "rule", "del", "priority", str(priority),
                     "fwmark", hex(mark), "lookup", str(table)]
        # Record intent first. If the process is interrupted, remove can still
        # clean only this exact table/rule, never unrelated administrator rules.
        state = {
            "owner": "adguard-vpn-desktop", "scope": scope, "level": level,
            "table": table, "mark": mark, "priority": priority,
            "ip_rule": ip_add, "phase": "intent",
        }
        self._write_state(state)
        nft_created = False
        ip_created = False
        try:
            self._exec(["nft", "-f", "-"], nft_batch)
            nft_created = True
            state["phase"] = "nft-created"
            self._write_state(state)
            self._exec(ip_add)
            ip_created = True
            state["phase"] = "active"
            self._write_state(state)
        except HelperError:
            if ip_created:
                _run(ip_delete, runner=self.runner)
            if nft_created:
                _run(["nft", "delete", "table", "inet", NFT_TABLE], runner=self.runner)
            try:
                self.state_file.unlink()
            except FileNotFoundError:
                pass
            raise
        return {"active": True, "scope": scope, "table": table, "mark": hex(mark), "priority": priority}

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
        # Delete exact owned rule if present; tolerate absence during recovery.
        _run(ip_delete, runner=self.runner)
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
