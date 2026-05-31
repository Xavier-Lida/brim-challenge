"""Employee roster for map, chat pickers, and other UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.deps import supabase_client
from api.supabase_io import list_employees

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("")
def get_employees(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_employees(client)
