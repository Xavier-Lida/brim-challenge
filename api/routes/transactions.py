"""Transactions list + a live "what-if" mock transaction tester for the demo."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.deps import supabase_client
from api.supabase_io import (
    apply_brim_categories,
    employee_name_map,
    get_mcc_category_map,
    list_transactions_page,
    load_active_policy,
)
from feature2 import run as run_compliance
from feature3 import APPROVAL_THRESHOLD_CAD, DENY_WEIGHT, FLAG_NOTIFY_WEIGHT

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def get_transactions(
    limit: int = Query(30, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    return list_transactions_page(client, limit=limit, offset=offset)


# --------------------------------------------------------------------------- #
# "What-if" transaction tester — evaluate one card charge against the live
# policy IN ISOLATION (dry run: no insert, deterministic, repeatable). Shows
# instantly whether it auto-passes or is routed to the finance approver.
# --------------------------------------------------------------------------- #


def _dedup_flags(raw_flags: list[dict]) -> list[dict]:
    """Collapse flags that share a warning message (keep the highest weight), ranked."""
    best: dict[str, dict] = {}
    for f in raw_flags:
        msg = f.get("warning_message") or ""
        w = int(f.get("weight") or 0)
        if msg not in best or w > best[msg]["weight"]:
            best[msg] = {"warning_message": msg, "weight": w, "policy_name": f.get("policy_name")}
    return sorted(best.values(), key=lambda x: x["weight"], reverse=True)


class MockTransactionBody(BaseModel):
    amount: float = Field(gt=0)
    merchant_name: str
    merchant_category: str = Field(description="MCC code, e.g. '5812'")
    city: str | None = None
    zipcode: str | None = None
    date: str | None = None          # ISO date/datetime; defaults to now
    employee_id: str | None = None   # display only (dry run never inserts)
    status: str = "pending"


@router.post("/mock")
def create_mock_transaction(
    body: MockTransactionBody,
    mock_llm: bool = Query(True, alias="mock_llm"),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    """Score a single card charge against the active policy and return the verdict."""
    names = employee_name_map(client)
    employee_id = str(body.employee_id) if body.employee_id else (next(iter(names), "") or "demo-emp")
    employee_name = names.get(employee_id, "Demo employee")

    tx_id = f"mock-{uuid.uuid4().hex[:10]}"
    date_str = body.date or datetime.now(timezone.utc).isoformat()

    # Single-row frame scored in isolation: per-transaction rules fire (threshold,
    # category limit, restricted, alcohol/personal, boosters) but history-based
    # detectors (split/duplicate/velocity/geo) can't false-positive on one row.
    df = pd.DataFrame([{
        "id": tx_id,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "department": "",
        "date": date_str,
        "amount": float(body.amount),
        "merchant_name": body.merchant_name,
        "merchant_category": str(body.merchant_category),
        "city": body.city or "",
        "zipcode": body.zipcode or "",
        "status": body.status,
    }])
    cat_map = get_mcc_category_map(client)
    df = apply_brim_categories(df, cat_map)
    brim_category = str(df.iloc[0]["brim_category"])

    policy = load_active_policy(client)
    try:
        out = run_compliance(df, policy, not mock_llm)
    except Exception:  # noqa: BLE001 — never hard-fail; fall back to deterministic
        out = run_compliance(df, policy, False)

    raw_flags = [
        f for f in (out.get("transaction_flags") or [])
        if str(f.get("transaction_id")) == tx_id
    ]
    max_w = max((float(f.get("weight") or 0) for f in raw_flags), default=0.0)

    try:
        threshold = float(policy.get("approval_threshold_cad", APPROVAL_THRESHOLD_CAD) or APPROVAL_THRESHOLD_CAD)
    except (TypeError, ValueError):
        threshold = APPROVAL_THRESHOLD_CAD

    over_threshold = float(body.amount) > threshold
    needs_approval = over_threshold or max_w >= FLAG_NOTIFY_WEIGHT

    if needs_approval:
        verdict = "needs_approval"
        if max_w >= DENY_WEIGHT:
            summary = f"⚠️ Routed to the finance approver — serious policy concern (severity {int(max_w)})."
        elif raw_flags:
            summary = f"⚠️ Routed to the finance approver — {len(raw_flags)} compliance flag(s) raised."
        else:
            summary = (f"⚠️ Routed to the finance approver — ${body.amount:,.2f} is over the "
                       f"${threshold:,.0f} pre-approval threshold.")
    else:
        verdict = "auto_pass"
        summary = (f"✅ Auto-approved — within policy and under the ${threshold:,.0f} threshold; "
                   f"no finance sign-off needed.")

    return {
        "transaction": {
            "id": tx_id,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "date": date_str,
            "amount": float(body.amount),
            "merchant_name": body.merchant_name,
            "merchant_category": str(body.merchant_category),
            "brim_category": brim_category,
            "city": body.city,
            "status": body.status,
        },
        "flags": _dedup_flags(raw_flags),
        "needs_approval": needs_approval,
        "verdict": verdict,
        "over_threshold": over_threshold,
        "threshold_cad": threshold,
        "summary": summary,
    }
