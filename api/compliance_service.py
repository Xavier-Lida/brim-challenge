"""Shared compliance scan execution for routes and policy mutations."""

from __future__ import annotations

from typing import Any

from api.supabase_io import (
    load_active_policy,
    load_transactions_frame,
    persist_compliance_output,
)
from feature2 import run as run_compliance


def execute_compliance_scan(
    client,
    *,
    mock_llm: bool = False,
    limit: int | None = None,
    replace: bool = True,
) -> dict[str, Any]:
    """Run Feature 2 on Supabase data and persist flags (optionally replacing prior flags)."""
    use_llm = not mock_llm
    df = load_transactions_frame(client)
    if limit is not None and limit < len(df):
        df = df.head(limit)
    transaction_ids = df["id"].astype(str).tolist()

    try:
        policy = load_active_policy(client)
        out = run_compliance(df, policy, use_llm)
    except Exception:  # noqa: BLE001
        policy = load_active_policy(client)
        out = run_compliance(df, policy, use_llm=False)

    stats = persist_compliance_output(
        client,
        out,
        transaction_ids=transaction_ids if replace else None,
        replace=replace,
    )
    return {
        "feature": "2 - Policy Compliance Engine",
        "flag_count": len(out.get("transaction_flags", [])),
        "strike_count": len(out.get("employee_strikes", [])),
        "summary": out.get("summary"),
        "persisted": stats,
    }
