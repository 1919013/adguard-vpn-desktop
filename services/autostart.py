"""Per-user XDG autostart management for the GUI and AdGuard VPN CLI."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _desktop_quote(value: str) -> str:
    """Quote one argument according to the Desktop Entry Exec field rules."""
    value = (value.replace("\\", "\\\\").replace('"', '\\"')
             .replace(chr(96), "\\" + chr(96)).replace("$", "\\$").replace("%", "%%"))
    return '"' + value + '"'


def _write_entry(directory: Path, entry_path: Path, name: str,
                 comment: str, command: list[str]) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    exec_line = " ".join(_desktop_quote(part) for part in command)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Comment={comment}\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    fd, temporary = tempfile.mkstemp(prefix=".adguard-autostart-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, entry_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return entry_path


class AutostartManager:
    """Manage only this GUI's per-user XDG autostart entry."""

    def __init__(self, entry_path: Path | None = None, main_path: Path | None = None):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.directory = config_home / "autostart"
        self.entry_path = entry_path or self.directory / "adguard-vpn-desktop.desktop"
        if entry_path is not None:
            self.directory = self.entry_path.parent
        self.main_path = (main_path or Path(__file__).resolve().parents[1] / "main.py").resolve()

    def enabled(self) -> bool:
        return self.entry_path.is_file()

    def enable(self) -> Path:
        if not self.main_path.is_file():
            raise FileNotFoundError(f"Не найден файл запуска приложения: {self.main_path}")
        return _write_entry(
            self.directory, self.entry_path,
            "ADGuard VPN Desktop",
            "Independent graphical interface for AdGuard VPN CLI",
            [sys.executable or "python3", str(self.main_path)],
        )

    def disable(self) -> bool:
        try:
            self.entry_path.unlink()
            return True
        except FileNotFoundError:
            return False


class VPNCLIAutostartManager:
    """Start AdGuard VPN CLI at user login with its reconnect-on-boot option."""

    def __init__(self, entry_path: Path | None = None, binary_path: str | None = None,
                 help_runner=None):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.directory = config_home / "autostart"
        self.entry_path = entry_path or self.directory / "adguard-vpn-cli.desktop"
        if entry_path is not None:
            self.directory = self.entry_path.parent
        self.binary_path = binary_path
        self.help_runner = help_runner or subprocess.run

    def enabled(self) -> bool:
        return self.entry_path.is_file()

    def _binary(self) -> str:
        binary = self.binary_path or shutil.which("adguardvpn-cli")
        if not binary:
            raise FileNotFoundError("Не найден adguardvpn-cli. Сначала установите официальный AdGuard VPN CLI.")
        return str(Path(binary).resolve())

    def enable(self) -> Path:
        binary = self._binary()
        try:
            result = self.help_runner(
                [binary, "connect", "--help"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Не удалось проверить поддержку параметра --boot: {exc}") from exc
        help_text = result.stdout or ""
        if "--boot" not in help_text:
            raise RuntimeError(
                "Установленная версия AdGuard VPN CLI не подтвердила поддержку --boot. "
                "Автозагрузка VPN не настроена."
            )
        return _write_entry(
            self.directory, self.entry_path,
            "AdGuard VPN CLI",
            "Connect AdGuard VPN at desktop login and keep reconnecting",
            [binary, "connect", "-y", "--boot"],
        )

    def disable(self) -> bool:
        try:
            self.entry_path.unlink()
            return True
        except FileNotFoundError:
            return False
