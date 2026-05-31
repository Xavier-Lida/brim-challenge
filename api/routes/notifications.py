"""In-app notifications routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import supabase_client
from api.supabase_io import list_notifications, mark_notification_read

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def get_notifications(
    unread: bool = Query(False),
    client=Depends(supabase_client),
) -> list[dict[str, Any]]:
    return list_notifications(client, unread_only=unread)


@router.patch("/{notification_id}/read")
def read_notification(
    notification_id: str,
    client=Depends(supabase_client),
) -> dict[str, Any]:
    try:
        row = mark_notification_read(client, notification_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": notification_id, "read": row.get("read", True)}
