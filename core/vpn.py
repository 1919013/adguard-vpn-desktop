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
        code, output = self.runner(["disconnect"], timeout=45)
        if code == 0:
            # Remove only ADGuard VPN Desktop's private policy-routing objects.
            # The saved route hook remains installed for the next connection.
            try:
                from services.app_routing import state_path, cleanup_kernel_state
                if state_path().is_file():
                    cleanup_code, cleanup_output = cleanup_kernel_state()
                    if cleanup_code:
                        return cleanup_code, (
                            (output + "\\n") if output else ""
                        ) + "VPN отключён, но не удалось очистить правила раздельного туннелирования: " + cleanup_output
                    output = (output + "\\n" if output else "") + cleanup_output
            except Exception as exc:
                return 1, (output + "\\n" if output else "") + f"VPN отключён, ошибка очистки маршрутов: {exc}"
        return code, output
