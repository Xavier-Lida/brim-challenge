"""Feature 2 — compliance scan routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import supabase_client
from api.supabase_io import (
    load_active_policy,
    load_transactions_frame,
    persist_compliance_output,
)
from feature2 import run

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.post("/scan")
def scan_compliance(
    mock_llm: bool = Query(False, alias="mock_llm"),
    limit: int | None = Query(None, ge=1),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    use_llm = not mock_llm
    try:
        df = load_transactions_frame(client)
        if limit is not None and limit < len(df):
            df = df.head(limit)
        policy = load_active_policy(client)
        out = run(df, policy, use_llm)
    except Exception as exc:  # noqa: BLE001
        try:
            df = load_transactions_frame(client)
            if limit is not None and limit < len(df):
                df = df.head(limit)
            policy = load_active_policy(client)
            out = run(df, policy, use_llm=False)
        except Exception as inner:
            raise HTTPException(status_code=500, detail=str(inner)) from inner

    stats = persist_compliance_output(client, out)
    return {
        "feature": "2 - Policy Compliance Engine",
        "flag_count": len(out.get("transaction_flags", [])),
        "strike_count": len(out.get("employee_strikes", [])),
        "summary": out.get("summary"),
        "persisted": stats,
    }
