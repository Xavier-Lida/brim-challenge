"""Feature 4 — expense report generation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from api.deps import supabase_client
from api.report_pdf import render_report_pdf, report_pdf_filename
from api.supabase_io import (
    flags_dict_from_db,
    get_expense_report_detail,
    list_expense_reports_page,
    load_transactions_frame,
    persist_reports_output,
    strikes_dict_from_db,
)
from feature4 import GROUP_GAP_DAYS, build_reports

router = APIRouter(prefix="/api/reports", tags=["reports"])


class GenerateReportsBody(BaseModel):
    event_group_id: str | None = None


@router.get("")
def get_reports(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    return list_expense_reports_page(client, limit=limit, offset=offset)


@router.get("/{report_id}/pdf")
def get_report_pdf(report_id: str, client=Depends(supabase_client)) -> Response:
    report = get_expense_report_detail(client, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No report with id={report_id}")
    pdf_bytes = render_report_pdf(report)
    filename = report_pdf_filename(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
