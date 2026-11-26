"""VPN lifecycle orchestration with non-blocking last-known-good location fallback."""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone

from core.commands import run_cli
from core.servers import (
    load_location_cache,
    parse_locations,
    save_location_cache,
)

Runner = Callable[..., tuple[int, str]]
_LOCATION_REFRESH_LOCK = threading.Lock()


class VPNService:
    """Small, UI-independent interface to AdGuard VPN CLI."""

    def __init__(self, runner: Runner = run_cli):
        self.runner = runner

    def status(self) -> tuple[int, str]:
        return self.runner(["status"], timeout=10)

    def cached_locations(self) -> tuple[list[dict], str | None]:
        return load_location_cache()

    def list_locations(self) -> tuple[int, str, list[dict], bool, str | None]:
        """Refresh using the supported CLI command; fall back to disk on any failure.

        The short timeout bounds a refresh attempt. A lock prevents overlapping
        refresh requests from a manual click and the periodic timer.
        """
        cached, cached_at = load_location_cache()
        if not _LOCATION_REFRESH_LOCK.acquire(blocking=False):
            return (0, "Обновление списка уже выполняется.", cached, bool(cached), cached_at)
        try:
            code, output = self.runner(["list-locations"], timeout=12)
            fresh = parse_locations(output) if code == 0 else []
            if fresh:
                updated_at = datetime.now(timezone.utc).isoformat()
                save_location_cache(fresh, updated_at)
                return 0, output, fresh, False, updated_at
            if cached:
                reason = output or "CLI вернул пустой или нераспознанный список."
                return code or 1, reason, cached, True, cached_at
            reason = output or "Список локаций недоступен; локального сохранённого списка пока нет."
            return code or 1, reason, [], False, None
        finally:
            _LOCATION_REFRESH_LOCK.release()

    def connect(self, city: str | None = None) -> tuple[int, str]:
        if city is not None:
            city = city.strip()
            if not city:
                return 2, "Название города не может быть пустым."
            return self.runner(["connect", "-l", city], timeout=90)
        return self.runner(["connect"], timeout=90)

    def disconnect(self) -> tuple[int, str]:
        return self.runner(["disconnect"], timeout=45)
