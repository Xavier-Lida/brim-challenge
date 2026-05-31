"""Transactions list + a live "mock transaction" injector for the demo."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.compliance_service import execute_compliance_scan
from api.deps import supabase_client
from api.supabase_io import (
    employee_name_map,
    get_mcc_category_map,
    list_transactions_page,
    load_active_policy,
)
from feature3 import APPROVAL_THRESHOLD_CAD, DENY_WEIGHT, FLAG_NOTIFY_WEIGHT
from feature4 import DEFAULT_BRIM_CATEGORY, _normalize_mcc

logger = logging.getLogger("brim.transactions")

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def get_transactions(
    limit: int = Query(30, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    return list_transactions_page(client, limit=limit, offset=offset)


# --------------------------------------------------------------------------- #
# Mock transaction injector — create a card transaction and get the live
# compliance + approval verdict in one round-trip (demo "what happens if…").
# --------------------------------------------------------------------------- #


class MockTransactionBody(BaseModel):
    amount: float = Field(gt=0)
    merchant_name: str
    merchant_category: str = Field(description="MCC code, e.g. '5812'")
    city: str | None = None
    zipcode: str | None = None
    date: str | None = None          # ISO date/datetime; defaults to now
    employee_id: str | None = None   # defaults to the first employee
    status: str = "pending"


@router.post("/mock")
def create_mock_transaction(
    body: MockTransactionBody,
    mock_llm: bool = Query(True, alias="mock_llm"),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    """Insert a mock card transaction, run compliance + approval, return the verdict."""
    names = employee_name_map(client)
    employee_id = str(body.employee_id) if body.employee_id else (next(iter(names), "") or "")
    if not employee_id:
        raise HTTPException(status_code=400, detail="No employees in the database to attribute the transaction to.")
    employee_name = names.get(employee_id, employee_id)

    tx_id = f"mock-{uuid.uuid4().hex[:10]}"
    date_str = body.date or datetime.now(timezone.utc).isoformat()
    row = {
        "id": tx_id,
        "employee_id": employee_id,
        "date": date_str,
        "amount": float(body.amount),
        "merchant_name": body.merchant_name,
        "merchant_category": str(body.merchant_category),
        "city": body.city,
        "zipcode": body.zipcode,
        "status": body.status,
    }
    try:
        client.table("transactions").insert([{k: v for k, v in row.items() if v is not None}]).execute()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Insert failed: {exc}") from exc

    # Scan this employee's transactions (incl. the new one) so contextual detectors
    # (split / duplicate / velocity / escalation …) can fire against their history.
    try:
        execute_compliance_scan(client, mock_llm=mock_llm, replace=True, employee_id=employee_id)
    except Exception as exc:  # noqa: BLE001 — never fail the demo on a scan hiccup
        logger.warning("mock tx compliance scan failed: %s", exc)

    # select("*") so the query never breaks on a column that may not exist on this
    # schema variant (e.g. policy_name lives on `policies`, not transaction_flags).
    fl = (
        client.table("transaction_flags")
        .select("*")
        .eq("transaction_id", tx_id)
        .execute()
    )
    flags = fl.data or []
    max_w = max((float(f.get("weight") or 0) for f in flags), default=0.0)

    policy = load_active_policy(client)
    try:
        threshold = float(policy.get("approval_threshold_cad", APPROVAL_THRESHOLD_CAD) or APPROVAL_THRESHOLD_CAD)
    except (TypeError, ValueError):
        threshold = APPROVAL_THRESHOLD_CAD

    over_threshold = float(body.amount) > threshold
    needs_approval = over_threshold or max_w >= FLAG_NOTIFY_WEIGHT

    cat_map = get_mcc_category_map(client)
    brim_category = cat_map.get(_normalize_mcc(body.merchant_category) or "", DEFAULT_BRIM_CATEGORY)

    if needs_approval:
        verdict = "needs_approval"
        if max_w >= DENY_WEIGHT:
            summary = f"⚠️ Routed to the finance approver — serious policy concern (severity {int(max_w)})."
        elif flags:
            summary = f"⚠️ Routed to the finance approver — {len(flags)} compliance flag(s) raised."
        else:
            summary = (f"⚠️ Routed to the finance approver — ${body.amount:,.2f} is over the "
                       f"${threshold:,.0f} approval threshold.")
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
        "flags": [
            {
                "warning_message": f.get("warning_message"),
                "weight": int(f.get("weight") or 0),
                "policy_name": f.get("policy_name"),
            }
            for f in sorted(flags, key=lambda x: float(x.get("weight") or 0), reverse=True)
        ],
        "needs_approval": needs_approval,
        "verdict": verdict,
        "over_threshold": over_threshold,
        "threshold_cad": threshold,
        "summary": summary,
    }
