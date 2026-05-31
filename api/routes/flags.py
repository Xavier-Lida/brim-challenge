"""Transaction flags CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.deps import supabase_client
from api.supabase_io import list_flags_enriched

try:
    from postgrest.exceptions import APIError as PostgrestAPIError
except ImportError:
    PostgrestAPIError = None  # type: ignore[misc, assignment]

router = APIRouter(prefix="/api/flags", tags=["flags"])

_REVIEWED_MIGRATION_HINT = (
    "Missing column transaction_flags.reviewed — run "
    "supabase/migrations/20260531_transaction_flags_reviewed.sql "
    "in Supabase SQL Editor"
)


def _reviewed_column_missing(exc: BaseException) -> bool:
    if PostgrestAPIError is not None and isinstance(exc, PostgrestAPIError):
        code = str(getattr(exc, "code", "") or "")
        if code == "PGRST204":
            return "reviewed" in str(exc).lower()
    msg = str(exc).lower()
    return "pgrst204" in msg or (
        "reviewed" in msg and ("column" in msg or "schema cache" in msg)
    )


@router.get("")
def get_flags(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_flags_enriched(client)


@router.patch("/{flag_id}/reviewed")
def mark_flag_reviewed(flag_id: str, client=Depends(supabase_client)) -> dict[str, Any]:
    try:
        res = (
            client.table("transaction_flags")
            .update({"reviewed": True})
            .eq("id", flag_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        if _reviewed_column_missing(exc):
            raise HTTPException(status_code=503, detail=_REVIEWED_MIGRATION_HINT) from exc
        raise
    if not res.data:
        raise HTTPException(status_code=404, detail=f"Flag {flag_id} not found")
    return {"id": flag_id, "reviewed": True}
