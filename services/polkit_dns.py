"""Polkit client for the isolated temporary DNS helper."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

HELPER_PATH = Path("/usr/libexec/adguard-vpn-desktop-dns-helper")


class PolkitDNSError(RuntimeError):
    """The privileged DNS helper could not complete an operation."""


class PolkitDNSClient:
    def __init__(self, *, helper=HELPER_PATH, runner=subprocess.run):
        self.helper = Path(helper)
        self.runner = runner

    def _call(self, *args):
        if not self.helper.is_file() or not os.access(self.helper, os.X_OK):
            raise PolkitDNSError("Отдельный DNS-helper не установлен. Обновите пакет ADGuard VPN Desktop.")
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise PolkitDNSError("Не найден pkexec (Polkit).")
        try:
            result = self.runner(
                [pkexec, str(self.helper), *args],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=45, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PolkitDNSError(f"Не удалось выполнить DNS-helper: {exc}") from exc
        output = (result.stdout or "").strip()
        if result.returncode:
            try:
                payload = json.loads(output)
                detail = payload.get("error", output)
            except (json.JSONDecodeError, AttributeError):
                detail = output or f"pkexec завершился с кодом {result.returncode}"
            raise PolkitDNSError(detail)
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PolkitDNSError("DNS-helper вернул некорректный ответ.") from exc
        if not isinstance(data, dict):
            raise PolkitDNSError("DNS-helper вернул неожиданный формат.")
        return data

    def apply(self, tunnel: str, dns_servers=("46.243.231.30", "46.243.231.31")):
        args = ["apply", "--tunnel", tunnel]
        for server in dns_servers:
            args.extend(["--dns-server", server])
        return self._call(*args)

    def restore(self):
        return self._call("restore")
