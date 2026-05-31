"""Deterministic per-policy pass/fail checks for approval requests."""

from __future__ import annotations

from typing import Any

import pandas as pd

from api.approval_messages import (
    VIOLATION_SEP,
    format_budget_violation,
    format_category_limit_violation,
    format_restricted_category,
    format_restricted_merchant,
    format_threshold_violation,
)
from feature2 import APPROVED_STATUSES, _norm_merchant, _parse_requirements

BUDGET_POLICY_ID = "pol-department-budget"
BUDGET_POLICY_NAME = "Department budget"


def _evaluate_single_policy(row: pd.Series, policy: dict) -> dict[str, Any]:
    """Return one PolicyCheck for a single active policy row."""
    policy_id = str(policy.get("id") or "")
    policy_name = str(policy.get("policy_name") or policy_id)
    rules = _parse_requirements(policy.get("policy_requirements", ""))

    amount = float(row["amount"])
    category = str(row.get("brim_category") or "")
    merchant = _norm_merchant(row.get("merchant_name"))
    merchant_display = str(row.get("merchant_name") or "")
    status = str(row.get("status") or "").strip().lower()

    failures: list[str] = []

    threshold = rules.get("approval_threshold_cad")
    if threshold is not None:
        try:
            threshold_f = float(threshold)
            if amount > threshold_f and status not in APPROVED_STATUSES:
                failures.append(format_threshold_violation(amount, threshold_f, merchant_display))
        except (TypeError, ValueError):
            pass

    for cat_key, limit_raw in (rules.get("category_limits_cad") or {}).items():
        cat = str(cat_key)
        if category != cat:
            continue
        try:
            limit = float(limit_raw)
        except (TypeError, ValueError):
            continue
        if amount > limit:
            failures.append(format_category_limit_violation(amount, limit, cat, merchant_display))

    for restricted in rules.get("restricted_categories") or []:
        if category and category == str(restricted):
            failures.append(format_restricted_category(category))

    for restricted in rules.get("restricted_merchants") or []:
        rm = str(restricted).lower()
        if rm and rm in merchant:
            failures.append(format_restricted_merchant(merchant_display, rm))

    check: dict[str, Any] = {
        "policy_id": policy_id,
        "policy_name": policy_name,
        "status": "failed" if failures else "passed",
    }
    if failures:
        check["message"] = VIOLATION_SEP.join(failures)
    return check


def _budget_policy_check(row: pd.Series, budget: dict[str, Any] | None) -> dict[str, Any] | None:
    if not budget:
        return None
    amount = float(row["amount"])
    remaining = float(budget.get("remaining") or 0)
    check: dict[str, Any] = {
        "policy_id": BUDGET_POLICY_ID,
        "policy_name": BUDGET_POLICY_NAME,
        "status": "failed" if amount > remaining else "passed",
    }
    if amount > remaining:
        check["message"] = format_budget_violation(amount, budget)
    return check


def evaluate_policy_checks(
    row: pd.Series,
    active_policies: list[dict],
    budget: dict[str, Any] | None = None,
) -> list[dict]:
    """Return PolicyCheck[] ordered by effective_date DESC, then id ASC."""
    ordered = sorted(active_policies, key=lambda p: str(p.get("id") or ""))
    ordered = sorted(ordered, key=lambda p: str(p.get("effective_date") or ""), reverse=True)
    checks = [_evaluate_single_policy(row, policy) for policy in ordered]
    budget_check = _budget_policy_check(row, budget)
    if budget_check is not None:
        checks.append(budget_check)
    return checks
