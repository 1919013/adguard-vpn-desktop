"""VPN location discovery and selection."""
from __future__ import annotations

import re


_LOCATION_LINE = re.compile(r"^([A-Z]{2})\s+(.+?)\s{2,}(.+?)\s{2,}(\d+)\s*$")


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


def find_locations(query: str, locations: list[dict]) -> list[dict]:
    """Return locations matching a city, country, or ISO code fragment."""
    needle = (query or "").strip().casefold()
    if not needle:
        return []
    return [
        item for item in locations
        if needle in f"{item.get('city', '')} {item.get('country', '')} {item.get('iso', '')}".casefold()
    ]
