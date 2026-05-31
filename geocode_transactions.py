"""Backfill transactions.latitude/longitude by geocoding distinct cities.

Idempotent: cities already present in city_geocodes are skipped, and only rows
with NULL coordinates are updated.

Usage:
    py geocode_transactions.py            # geocode + update transactions
    py geocode_transactions.py --dry-run  # geocode/cache only, no transaction UPDATE
    py geocode_transactions.py --sleep 0.1
"""

from __future__ import annotations

import argparse
import sys
import time

from api.geocoding import (
    CACHE_TABLE,
    geocode_city,
    is_valid_city,
    normalize_city,
)
from api.supabase_io import fetch_table, get_supabase_client


def _already_cached(client) -> set[str]:
    try:
        res = client.table(CACHE_TABLE).select("city").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not read {CACHE_TABLE}: {exc}")
        return set()
    return {normalize_city(r.get("city")) for r in (res.data or [])}


def _update_city_coords(client, raw_cities: list[str], lat: float, lng: float) -> int:
    """Update all NULL-coord transactions whose city matches any raw spelling."""
    total = 0
    for raw in raw_cities:
        try:
            res = (
                client.table("transactions")
                .update({"latitude": lat, "longitude": lng})
                .eq("city", raw)
                .is_("latitude", "null")
                .execute()
            )
            total += len(res.data or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] update failed for city={raw!r}: {exc}")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="geocode + cache only, no UPDATE")
    ap.add_argument("--sleep", type=float, default=0.1, help="seconds between Mapbox calls")
    args = ap.parse_args()

    client = get_supabase_client()

    df = fetch_table(client, "transactions")
    if df.empty:
        print("No transactions.")
        return 0

    import pandas as pd

    for col in ("latitude", "longitude"):
        if col not in df.columns:
            df[col] = None
        df[col] = pd.to_numeric(df[col], errors="coerce")

    missing = df[df["latitude"].isna() | df["longitude"].isna()]
    if missing.empty:
        print("All transactions already have coordinates.")
        return 0

    # Map normalized city -> list of raw spellings (to match on UPDATE).
    raw_by_norm: dict[str, set[str]] = {}
    for raw in missing.get("city", pd.Series(dtype=str)).dropna().tolist():
        raw = str(raw)
        if is_valid_city(raw):
            raw_by_norm.setdefault(normalize_city(raw), set()).add(raw)

    cached = _already_cached(client)
    to_process = [k for k in raw_by_norm if k not in cached]

    print(
        f"{len(missing)} rows missing coords | {len(raw_by_norm)} valid distinct cities | "
        f"{len(to_process)} new to geocode ({len(cached)} cached)"
    )

    resolved = 0
    updated_rows = 0
    for i, norm in enumerate(sorted(to_process), 1):
        coords = geocode_city(norm, client)
        status = "ok" if coords else "unresolved"
        if coords:
            resolved += 1
        print(f"[{i}/{len(to_process)}] {norm}: {status}")
        if coords and not args.dry_run:
            updated_rows += _update_city_coords(client, sorted(raw_by_norm[norm]), *coords)
        if args.sleep:
            time.sleep(args.sleep)

    # Also backfill transactions for cities resolved in a previous run.
    if not args.dry_run:
        from api.geocoding import load_geocode_cache

        cache = load_geocode_cache(client)
        for norm, raws in raw_by_norm.items():
            if norm in to_process or norm not in cache:
                continue
            lat, lng = cache[norm]
            updated_rows += _update_city_coords(client, sorted(raws), lat, lng)

    print(f"\nDone. Newly resolved: {resolved}/{len(to_process)}. Transaction rows updated: {updated_rows}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
