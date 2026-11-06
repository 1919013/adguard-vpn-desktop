"""VPN lifecycle orchestration."""
from __future__ import annotations

import re
from collections.abc import Callable

from core.commands import run_cli
from core.servers import parse_locations

Runner = Callable[..., tuple[int, str]]


class VPNService:
    """Small, UI-independent interface to AdGuard VPN CLI."""

    def __init__(self, runner: Runner = run_cli):
        self.runner = runner

    def status(self) -> tuple[int, str]:
        return self.runner(["status"], timeout=10)

    def version(self) -> tuple[int, str]:
        return self.runner(["--version"], timeout=10)

    def check_update(self) -> tuple[int, str]:
        return self.runner(["check-update"], timeout=90)

    def update(self) -> tuple[int, str]:
        return self.runner(["update", "-y"], timeout=600)

    def config_show(self) -> tuple[int, str]:
        return self.runner(["config", "show"], timeout=15)

    def set_bound_interface(self, interface: str) -> tuple[int, str]:
        interface = interface.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
            return 2, "Недопустимое имя сетевого интерфейса."
        return self.runner(["config", "set-bound-if-override", interface], timeout=20)

    def clear_bound_interface(self) -> tuple[int, str]:
        return self.runner(["config", "set-bound-if-override", ""], timeout=20)

    def list_locations(self) -> tuple[int, str, list[dict]]:
        code, output = self.runner(["list-locations"], timeout=40)
        return code, output, parse_locations(output) if code == 0 else []

    def connect(self, city: str | None = None) -> tuple[int, str]:
        if city is not None:
            city = city.strip()
            if not city:
                return 2, "Название города не может быть пустым."
            return self.runner(["connect", "-l", city], timeout=90)
        return self.runner(["connect"], timeout=90)

    def disconnect(self) -> tuple[int, str]:
        return self.runner(["disconnect"], timeout=45)
