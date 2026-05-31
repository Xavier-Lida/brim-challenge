"""Transactions list for the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.deps import supabase_client
from api.supabase_io import fetch_table, list_flags_enriched

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def get_transactions(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    tx_df = fetch_table(client, "transactions")
    if tx_df.empty:
        return []

    emp_df = fetch_table(client, "employees")
    emp_names: dict[str, str] = {}
    if not emp_df.empty:
        for _, r in emp_df.iterrows():
            parts = [
                str(r.get(c, "")).strip()
                for c in ("first_name", "last_name")
                if c in emp_df.columns
            ]
            emp_names[str(r["id"])] = " ".join(p for p in parts if p).strip()

    flags = list_flags_enriched(client)
    flag_counts: dict[str, int] = {}
    for f in flags:
        tid = f["transaction_id"]
        flag_counts[tid] = flag_counts.get(tid, 0) + 1

    out: list[dict[str, Any]] = []
    for _, r in tx_df.iterrows():
        tid = str(r["id"])
        emp_id = str(r.get("employee_id", ""))
        status = str(r.get("status", "pending"))
        if flag_counts.get(tid, 0) > 0 and status == "pending":
            status = "flagged"
        out.append({
            "id": tid,
            "employee_id": emp_id,
            "employee_name": emp_names.get(emp_id, emp_id),
            "date": str(r.get("date", ""))[:10],
            "amount": float(r.get("amount", 0)),
            "merchant_name": str(r.get("merchant_name", "")),
            "merchant_category": str(r.get("merchant_category", "")),
            "city": str(r.get("city", "")),
            "status": status,
            "flag_count": flag_counts.get(tid, 0),
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    return out
