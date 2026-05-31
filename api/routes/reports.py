"""Feature 4 — expense report generation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import supabase_client
from api.supabase_io import (
    flags_dict_from_db,
    load_transactions_frame,
    persist_reports_output,
    strikes_dict_from_db,
    list_expense_reports,
)
from feature4 import GROUP_GAP_DAYS, build_reports

router = APIRouter(prefix="/api/reports", tags=["reports"])


class GenerateReportsBody(BaseModel):
    event_group_id: str | None = None


@router.get("")
def get_reports(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_expense_reports(client)


@router.post("/generate")
def generate_reports(
    body: GenerateReportsBody | None = None,
    mock_llm: bool = Query(False, alias="mock_llm"),
    gap_days: int = Query(GROUP_GAP_DAYS, ge=1),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    use_llm = not mock_llm
    body = body or GenerateReportsBody()

    df = load_transactions_frame(client)
    if body.event_group_id:
        mask = df["event_group_id"].astype(str) == str(body.event_group_id)
        if not mask.any():
            raise HTTPException(
                status_code=404,
                detail=f"No transactions for event_group_id={body.event_group_id}",
            )
        df = df[mask]
    else:
        unassigned = df["event_group_id"].isna() | (df["event_group_id"].astype(str) == "")
        df = df[unassigned] if unassigned.any() else df

    flags = flags_dict_from_db(client)
    strikes = strikes_dict_from_db(client)

    try:
        assignments, reports = build_reports(df, gap_days, flags, strikes, use_llm)
        mode = "llm" if use_llm else "mock"
    except Exception as exc:  # noqa: BLE001
        assignments, reports = build_reports(df, gap_days, flags, strikes, use_llm=False)
        mode = f"mock (fallback: {exc})"

    clean_reports = [{k: v for k, v in r.items() if not k.startswith("_")} for r in reports]
    stats = persist_reports_output(client, assignments, clean_reports)

    return {
        "feature": "4 - Expense Report Generation",
        "model": mode,
        "report_count": len(clean_reports),
        "transaction_event_groups": assignments,
        "expense_reports": clean_reports,
        "persisted": stats,
    }
