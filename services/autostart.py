"""Per-user XDG autostart management for ADGuard VPN Desktop."""
from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path


class AutostartManager:
    """Manage only this GUI's per-user XDG autostart entry."""

    def __init__(self, entry_path: Path | None = None, main_path: Path | None = None):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.directory = config_home / "autostart"
        self.entry_path = entry_path or self.directory / "adguard-vpn-desktop.desktop"
        self.main_path = (main_path or Path(__file__).resolve().parents[1] / "main.py").resolve()

    def enabled(self) -> bool:
        return self.entry_path.is_file()

    def enable(self) -> Path:
        if not self.main_path.is_file():
            raise FileNotFoundError(f"Не найден файл запуска приложения: {self.main_path}")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        python = shlex.quote(os.environ.get("PYTHON", "python3"))
        script = shlex.quote(str(self.main_path))
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=ADGuard VPN Desktop\n"
            "Comment=Independent graphical interface for AdGuard VPN CLI\n"
            f"Exec={python} {script}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        fd, temporary = tempfile.mkstemp(prefix=".adguard-vpn-desktop-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.entry_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return self.entry_path

    def disable(self) -> bool:
        try:
            self.entry_path.unlink()
            return True
        except FileNotFoundError:
            return False
