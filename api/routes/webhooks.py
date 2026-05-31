"""Supabase database webhook handler."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import supabase_client
from api.routes.approvals import _policy_threshold
from api.supabase_io import (
    flags_dict_from_db,
    load_active_policy,
    load_all_from_supabase,
    load_transactions_frame,
    persist_compliance_output,
    persist_pipeline_to_supabase,
    persist_reports_output,
    strikes_dict_from_db,
)
from feature2 import run as run_compliance
from feature3 import build_pipeline
from feature4 import GROUP_GAP_DAYS, build_reports

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookPayload(BaseModel):
    type: str
    table: str
    record: dict[str, Any]
    old_record: dict[str, Any] | None = None


def _employee_context_df(df, employee_id: str, transaction_id: str):
    """Transactions for compliance context: same employee, recent window."""
    import pandas as pd

    emp_mask = df["employee_id"].astype(str) == str(employee_id)
    subset = df[emp_mask].copy()
    if subset.empty:
        match = df[df["id"].astype(str) == str(transaction_id)]
        return match if not match.empty else df.head(1)
    subset["_d"] = pd.to_datetime(subset["date"], errors="coerce")
    anchor = subset[subset["id"].astype(str) == str(transaction_id)]
    if anchor.empty:
        return subset.tail(50)
    anchor_date = anchor.iloc[0]["_d"]
    if pd.isna(anchor_date):
        return subset.tail(50)
    window = subset[subset["_d"] >= anchor_date - pd.Timedelta(days=7)]
    return window if not window.empty else subset.tail(50)


@router.post("/supabase")
def handle_supabase_webhook(
    payload: WebhookPayload,
    client=Depends(supabase_client),
) -> dict[str, Any]:
    if payload.type != "INSERT" or payload.table != "transactions":
        return {"handled": False, "reason": "ignored event"}

    record = payload.record
    transaction_id = str(record.get("id", ""))
    employee_id = str(record.get("employee_id", ""))
    if not transaction_id or not employee_id:
        raise HTTPException(status_code=400, detail="Invalid transaction record")

    results: dict[str, Any] = {"transaction_id": transaction_id, "steps": []}

    # 1) Compliance scan (contextual subset)
    try:
        df = load_transactions_frame(client)
        policy = load_active_policy(client)
        scan_df = _employee_context_df(df, employee_id, transaction_id)
        compliance_out = run_compliance(scan_df, policy, use_llm=False)
        scan_ids = scan_df["id"].astype(str).tolist()
        compliance_stats = persist_compliance_output(
            client,
            compliance_out,
            transaction_ids=scan_ids,
            replace=True,
        )
        results["steps"].append({"compliance": compliance_stats})
    except Exception as exc:  # noqa: BLE001
        results["steps"].append({"compliance_error": str(exc)})

    # 2) Approval threshold check
    try:
        df_all, flags, strikes, budgets = load_all_from_supabase(client)
        threshold = _policy_threshold(client)
        approver_to = os.getenv("APPROVER_EMAIL", "approver@company.com")
        row_mask = df_all["id"].astype(str) == transaction_id
        approval_df = df_all[row_mask]
        if not approval_df.empty:
            approval_requests, notifications, _emails = build_pipeline(
                approval_df, flags, strikes, budgets, threshold, approver_to, use_llm=False
            )
            persist_pipeline_to_supabase(client, approval_requests, notifications)
            results["steps"].append({
                "approvals": len(approval_requests),
                "notifications": len(notifications),
            })
    except Exception as exc:  # noqa: BLE001
        results["steps"].append({"approval_error": str(exc)})

    # 3) Event grouping for unassigned employee transactions
    try:
        df = load_transactions_frame(client)
        emp_df = df[df["employee_id"].astype(str) == employee_id].copy()
        unassigned = emp_df["event_group_id"].isna() | (emp_df["event_group_id"].astype(str) == "")
        group_df = emp_df[unassigned] if unassigned.any() else emp_df.tail(10)
        flags = flags_dict_from_db(client)
        strikes = strikes_dict_from_db(client)
        assignments, reports = build_reports(group_df, GROUP_GAP_DAYS, flags, strikes, use_llm=False)
        if assignments:
            persist_reports_output(client, assignments, [])
            results["steps"].append({"event_groups_updated": len(assignments)})
    except Exception as exc:  # noqa: BLE001
        results["steps"].append({"grouping_error": str(exc)})

    results["handled"] = True
    return results
