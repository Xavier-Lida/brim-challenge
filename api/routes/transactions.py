"""Transactions list for the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import supabase_client
from api.supabase_io import list_transactions_page

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def get_transactions(
    limit: int = Query(30, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    return list_transactions_page(client, limit=limit, offset=offset)
