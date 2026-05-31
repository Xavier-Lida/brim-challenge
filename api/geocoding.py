"""City -> coordinates geocoding via Mapbox, with a Supabase + in-process cache.

Network calls happen only in geocode_city(). The API runtime should use
load_geocode_cache() which never hits the network.
"""

from __future__ import annotations

import os
import re

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"
CACHE_TABLE = "city_geocodes"

# Reject empty, "N/A", purely numeric, or phone-number-looking strings.
_PHONE_RE = re.compile(r"^[\d\s\-\+\(\)\.]{6,}$")
_INVALID_LITERALS = {"", "n/a", "na", "none", "null", "unknown", "-"}

# In-process memo: normalized city -> (lat, lng) or None (resolved-but-empty).
_MEMO: dict[str, tuple[float, float] | None] = {}


def _mapbox_token() -> str | None:
    return os.getenv("MAPBOX_ACCESS_TOKEN") or os.getenv("NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN")


def normalize_city(city: str | None) -> str:
    """Canonical key used consistently for cache writes and reads."""
    return (city or "").strip().upper()


def is_valid_city(city: str | None) -> bool:
    if city is None:
        return False
    raw = city.strip()
    if raw.lower() in _INVALID_LITERALS:
        return False
    if _PHONE_RE.match(raw):
        return False
    # Require at least one alphabetic character.
    return any(ch.isalpha() for ch in raw)


def _cache_get(client, key: str) -> tuple[bool, tuple[float, float] | None]:
    """Return (found, coords). coords is None when row exists but unresolved."""
    try:
        res = (
            client.table(CACHE_TABLE)
            .select("city, latitude, longitude, resolved")
            .eq("city", key)
            .limit(1)
            .execute()
        )
    except Exception:  # noqa: BLE001
        return False, None
    rows = res.data or []
    if not rows:
        return False, None
    row = rows[0]
    if row.get("resolved") and row.get("latitude") is not None and row.get("longitude") is not None:
        return True, (float(row["latitude"]), float(row["longitude"]))
    return True, None


def _cache_put(client, key: str, coords: tuple[float, float] | None) -> None:
    if client is None:
        return
    payload = {
        "city": key,
        "latitude": coords[0] if coords else None,
        "longitude": coords[1] if coords else None,
        "resolved": coords is not None,
    }
    try:
        client.table(CACHE_TABLE).upsert(payload, on_conflict="city").execute()
    except Exception:  # noqa: BLE001
        pass


def _call_mapbox(query: str) -> tuple[float, float] | None:
    token = _mapbox_token()
    if not token:
        return None

    from urllib.parse import quote

    url = MAPBOX_GEOCODE_URL.format(query=quote(query))
    try:
        import httpx

        resp = httpx.get(
            url,
            params={"types": "place", "limit": 1, "access_token": token},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None

    features = data.get("features") or []
    if not features:
        return None
    center = features[0].get("center") or []
    if len(center) != 2:
        return None
    lng, lat = float(center[0]), float(center[1])
    return (lat, lng)


def geocode_city(city: str | None, client=None) -> tuple[float, float] | None:
    """Resolve a city to (lat, lng). Uses memo + Supabase cache before Mapbox.

    When a row already exists in the cache (resolved or not) no network call is
    made. Errors/timeouts return None and never raise.
    """
    if not is_valid_city(city):
        return None
    key = normalize_city(city)

    if key in _MEMO:
        return _MEMO[key]

    if client is not None:
        found, coords = _cache_get(client, key)
        if found:
            _MEMO[key] = coords
            return coords

    coords = _call_mapbox(key)
    _MEMO[key] = coords
    _cache_put(client, key, coords)
    return coords


def load_geocode_cache(client) -> dict[str, tuple[float, float]]:
    """All resolved city -> (lat, lng) pairs. Never hits the network."""
    out: dict[str, tuple[float, float]] = {}
    if client is None:
        return out
    try:
        res = (
            client.table(CACHE_TABLE)
            .select("city, latitude, longitude, resolved")
            .eq("resolved", True)
            .execute()
        )
    except Exception:  # noqa: BLE001
        return out
    for row in res.data or []:
        lat, lng = row.get("latitude"), row.get("longitude")
        if lat is None or lng is None:
            continue
        out[normalize_city(row.get("city"))] = (float(lat), float(lng))
        # Warm the in-process memo too.
        _MEMO[normalize_city(row.get("city"))] = (float(lat), float(lng))
    return out
