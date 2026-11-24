"""Fixed-argument pkexec client for the installed root helper."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


HELPER_PATH = Path("/usr/libexec/adguard-vpn-desktop-helper")
SCOPE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\\.scope$")


class PolkitSplitTunnelError(RuntimeError):
    pass


class PolkitSplitTunnelClient:
    def __init__(self, *, helper: Path = HELPER_PATH, runner=subprocess.run):
        self.helper = Path(helper)
        self.runner = runner

    def _call(self, operation: str, *args: str) -> dict:
        if not self.helper.is_file() or not os.access(self.helper, os.X_OK):
            raise PolkitSplitTunnelError(
                "Привилегированный helper не установлен. Требуется установить пакет с polkit policy."
            )
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise PolkitSplitTunnelError("Не найден pkexec (polkit).")
        result = self.runner(
            [pkexec, str(self.helper), operation, *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=30, check=False,
        )
        output = (result.stdout or "").strip()
        if result.returncode:
            raise PolkitSplitTunnelError(output or f"pkexec завершился с кодом {result.returncode}")
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PolkitSplitTunnelError("Helper вернул некорректный ответ.") from exc
        if not isinstance(data, dict):
            raise PolkitSplitTunnelError("Helper вернул неожиданный формат ответа.")
        return data

    def apply(self, *, scope: str, level: int, table: int) -> dict:
        if not SCOPE_RE.fullmatch(scope):
            raise PolkitSplitTunnelError("Недопустимое имя systemd scope.")
        if not 1 <= int(level) <= 32 or not 1 <= int(table) <= 2**31 - 1:
            raise PolkitSplitTunnelError("Недопустимые параметры маршрутизации.")
        return self._call("apply", "--scope", scope, "--level", str(level), "--table", str(table))

    def verify(self, *, scope: str, level: int, table: int) -> bool:
        result = self._call("verify", "--scope", scope, "--level", str(level), "--table", str(table))
        return result.get("ready") is True

    def remove(self) -> dict:
        return self._call("remove")
