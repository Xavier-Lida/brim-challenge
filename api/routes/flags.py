"""Transaction flags CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.deps import supabase_client
from api.supabase_io import list_flags_enriched

router = APIRouter(prefix="/api/flags", tags=["flags"])


@router.get("")
def get_flags(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_flags_enriched(client)


@router.patch("/{flag_id}/reviewed")
def mark_flag_reviewed(flag_id: str, client=Depends(supabase_client)) -> dict[str, Any]:
    res = (
        client.table("transaction_flags")
        .update({"reviewed": True})
        .eq("id", flag_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail=f"Flag {flag_id} not found")
    return {"id": flag_id, "reviewed": True}
