"""Purchase map view for the Reports section."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import supabase_client
from api.supabase_io import build_map_purchases, list_map_employees

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/employees")
def get_map_employees(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_map_employees(client)


@router.get("/purchases")
def get_map_purchases(
    employee_ids: str = Query(""),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    ids = [s.strip() for s in employee_ids.split(",") if s.strip()]
    return build_map_purchases(client, ids, date_from, date_to)
