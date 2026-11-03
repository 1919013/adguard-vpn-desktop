"""VPN lifecycle orchestration."""
from __future__ import annotations

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
