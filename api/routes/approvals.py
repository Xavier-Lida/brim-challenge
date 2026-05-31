"""Feature 3 — approval pipeline routes."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import supabase_client
from api.supabase_io import (
    apply_decision_to_supabase,
    list_approvals_enriched,
    load_all_from_supabase,
    persist_pipeline_to_supabase,
)
from feature3 import (
    APPROVAL_THRESHOLD_CAD,
    build_pipeline,
    process_decision,
    send_email_resend,
)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalDecisionBody(BaseModel):
    status: Literal["approved", "denied"]
    approver_id: str | None = None


@router.get("")
def get_approvals(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_approvals_enriched(client)


@router.post("/run")
def run_approvals_pipeline(
    mock_llm: bool = Query(False, alias="mock_llm"),
    threshold: float = Query(APPROVAL_THRESHOLD_CAD, gt=0),
    send: bool = Query(False),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    use_llm = not mock_llm
    approver_to = os.getenv("APPROVER_EMAIL", "approver@company.com")
    from_addr = os.getenv("RESEND_FROM", "Brim <noreply@company.com>")

    df, flags, strikes, budgets = load_all_from_supabase(client)
    try:
        approval_requests, notifications, emails = build_pipeline(
            df, flags, strikes, budgets, threshold, approver_to, use_llm
        )
        mode = "llm" if use_llm else "mock"
    except Exception as exc:  # noqa: BLE001
        approval_requests, notifications, emails = build_pipeline(
            df, flags, strikes, budgets, threshold, approver_to, use_llm=False
        )
        mode = f"mock (fallback: {exc})"

    if send:
        for em in emails:
            em["sent"] = send_email_resend(em, from_addr)

    persist_pipeline_to_supabase(client, approval_requests, notifications)

    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in approval_requests]
    return {
        "feature": "3 - Approval Notifications",
        "model": mode,
        "approval_request_count": len(clean),
        "notification_count": len(notifications),
        "approval_requests": clean,
    }


@router.patch("/{approval_id}")
def decide_approval(
    approval_id: str,
    body: ApprovalDecisionBody,
    client=Depends(supabase_client),
) -> dict[str, Any]:
    req_res = client.table("approval_requests").select("transaction_id").eq("id", approval_id).execute()
    if not req_res.data:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")

    transaction_id = str(req_res.data[0]["transaction_id"])
    decision = "approve" if body.status == "approved" else "deny"
    employee_to = os.getenv("EMPLOYEE_EMAIL", "employee@company.com")

    df, flags, strikes, budgets = load_all_from_supabase(client)
    result = process_decision(
        df,
        flags,
        strikes,
        budgets,
        APPROVAL_THRESHOLD_CAD,
        transaction_id,
        decision,
        body.approver_id,
        employee_to,
    )
    apply_decision_to_supabase(client, result)
    return {
        "approval_id": approval_id,
        "status": body.status,
        "transaction_id": transaction_id,
    }
