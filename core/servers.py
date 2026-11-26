"""VPN location discovery, selection and durable last-known-good cache."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_LOCATION_LINE = re.compile(r"^([A-Z]{2})\s+(.+?)\s{2,}(.+?)\s{2,}(\d+)\s*$")
_ALLOWED_INTERVALS = (0, 30, 60)


def _state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "adguard-vpn-desktop"


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".locations-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def parse_locations(output: str) -> list[dict]:
    """Parse the column-aligned output of AdGuard VPN CLI 1.8.x."""
    locations = []
    for line in (output or "").splitlines():
        value = line.strip()
        if not value or value.upper().startswith("ISO"):
            continue
        match = _LOCATION_LINE.match(value)
        if not match:
            continue
        iso, country, city, ping = match.groups()
        country, city = country.strip(), city.strip()
        locations.append({
            "iso": iso,
            "country": country,
            "city": city,
            "ping": int(ping),
            "label": f"{city}, {country} — {ping} мс",
        })
    return locations


def _valid_locations(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        iso, country, city = item.get("iso"), item.get("country"), item.get("city")
        ping = item.get("ping", 0)
        if (not isinstance(iso, str) or not re.fullmatch(r"[A-Z]{2}", iso)
                or not isinstance(country, str) or not country.strip()
                or not isinstance(city, str) or not city.strip()
                or not isinstance(ping, int) or isinstance(ping, bool) or ping < 0):
            continue
        valid.append({
            "iso": iso, "country": country.strip(), "city": city.strip(),
            "ping": ping,
            "label": str(item.get("label") or f"{city.strip()}, {country.strip()} — {ping} мс"),
        })
    return valid


def load_location_cache() -> tuple[list[dict], str | None]:
    """Load the last-known-good location list without making a network request."""
    path = _state_dir() / "locations.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        locations = _valid_locations(data.get("locations") if isinstance(data, dict) else None)
        updated_at = data.get("updated_at") if isinstance(data, dict) else None
        if locations and isinstance(updated_at, str):
            return locations, updated_at
    except (OSError, ValueError, TypeError):
        pass
    return [], None


def save_location_cache(locations: list[dict], updated_at: str | None = None) -> bool:
    """Atomically replace cache only with a non-empty, validated server list."""
    valid = _valid_locations(locations)
    if not valid:
        return False
    try:
        _atomic_json(_state_dir() / "locations.json", {
            "schema": 1,
            "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
            "locations": valid,
        })
        return True
    except OSError:
        return False


def load_refresh_interval() -> int:
    path = _state_dir() / "preferences.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("location_refresh_minutes", 30)
        return value if value in _ALLOWED_INTERVALS else 30
    except (OSError, ValueError, TypeError, AttributeError):
        return 30


def save_refresh_interval(minutes: int) -> bool:
    if minutes not in _ALLOWED_INTERVALS:
        return False
    path = _state_dir() / "preferences.json"
    current = {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError, TypeError):
        pass
    current["location_refresh_minutes"] = minutes
    try:
        _atomic_json(path, current)
        return True
    except OSError:
        return False


def find_locations(query: str, locations: list[dict]) -> list[dict]:
    """Return locations matching a city, country, or ISO code fragment."""
    needle = (query or "").strip().casefold()
    if not needle:
        return []
    return [
        item for item in locations
        if needle in f"{item.get('city', '')} {item.get('country', '')} {item.get('iso', '')}".casefold()
    ]
