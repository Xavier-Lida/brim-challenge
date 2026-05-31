"""User-friendly English message builders for approval cards and policy checks."""

from __future__ import annotations

from typing import Any

VIOLATION_SEP = " · "

CATEGORY_LABELS: dict[str, str] = {
    "Repas Personnel": "personal meal",
    "Repas Client": "client or team meal",
    "Voyage": "travel",
    "Transport Local": "local transport",
    "Logiciel / IT": "software / IT",
    "Carburant": "fuel",
    "Fournitures de bureau": "office supplies",
    "Télécommunications": "telecommunications",
    "Autre": "other",
}


def format_money(amount: float) -> str:
    return f"${amount:,.2f} CAD"


def category_label(category: str) -> str:
    if not category:
        return "expense"
    return CATEGORY_LABELS.get(category, category)


def _merchant_label(merchant: str | None) -> str:
    if merchant and str(merchant).strip():
        return str(merchant).strip()
    return "this merchant"


def format_threshold_violation(amount: float, threshold: float, merchant: str | None) -> str:
    over = max(0.0, amount - threshold)
    place = _merchant_label(merchant)
    return (
        f"This {format_money(amount)} charge at {place} is {format_money(over)} over the "
        f"{format_money(threshold)} pre-approval limit. Manager sign-off is required."
    )


def format_category_limit_violation(
    amount: float, limit: float, category: str, merchant: str | None,
) -> str:
    over = max(0.0, amount - limit)
    label = category_label(category)
    place = _merchant_label(merchant)
    return (
        f"This {label} expense of {format_money(amount)} at {place} exceeds the "
        f"{format_money(limit)} limit by {format_money(over)}."
    )


def format_restricted_category(category: str) -> str:
    label = category_label(category)
    return f'The "{label}" category is not allowed on the corporate card.'


def format_restricted_merchant(merchant: str | None, matched_rule: str) -> str:
    place = _merchant_label(merchant)
    return (
        f'Charges at "{place}" are not permitted — this merchant matches the '
        f'restricted vendor rule "{matched_rule}".'
    )


def format_budget_violation(amount: float, budget: dict[str, Any]) -> str:
    remaining = float(budget.get("remaining") or 0)
    over = max(0.0, amount - remaining)
    quarter = budget.get("quarter") or ""
    year = budget.get("year") or ""
    period = f"{quarter} {year}".strip() or "this quarter"
    return (
        f"This {format_money(amount)} request exceeds the department's remaining "
        f"{format_money(remaining)} budget for {period} by {format_money(over)}."
    )


def _format_flag_message(flag: dict, amount: float, merchant: str | None) -> str:
    msg = str(flag.get("warning_message") or "").strip()
    weight = int(flag.get("weight") or 0)
    lower = msg.lower()
    place = _merchant_label(merchant)

    if "split" in lower and "merchant" in lower:
        return (
            f"Possible split purchase detected at {place}: multiple charges were combined "
            f"to stay under the approval threshold. Review whether this was intentional."
        )
    if "duplicate" in lower:
        return (
            f"A possible duplicate charge of {format_money(amount)} at {place} was detected. "
            f"Confirm this expense has not already been submitted."
        )
    if "pre-approval threshold" in lower or "at/above" in lower:
        return format_threshold_violation(amount, _extract_threshold(msg, 500.0), merchant)
    if "exceeds the" in lower and "limit for" in lower:
        limit = _extract_amount_after(msg, "exceeds the $", default=0.0)
        return (
            f"This {format_money(amount)} charge at {place} exceeds a category spending limit "
            f"by {format_money(max(0.0, amount - limit)) if limit else format_money(amount)}."
        )
    if "restricted under the expense policy" in lower or "category" in lower and "restricted" in lower:
        return "This expense category is restricted under company policy."
    if "restricted list" in lower or "on the restricted" in lower:
        return format_restricted_merchant(merchant, "restricted vendor")
    if "round-number" in lower or "round number" in lower:
        return (
            f"This {format_money(amount)} charge at {place} uses a round dollar amount, "
            f"which can indicate a manual or unusual entry (severity {weight}/5)."
        )
    if "velocity" in lower or "concentrated activity" in lower:
        return (
            f"Unusually high purchase velocity involving {place}: many charges by this employee "
            f"in a single day. Confirm the spending burst is legitimate."
        )
    if "geographic anomaly" in lower or "different cities" in lower or "implausible" in lower:
        return (
            f"Geographic anomaly: this employee charged in multiple cities on the same day, which "
            f"is physically implausible. Verify the {format_money(amount)} charge at {place}."
        )
    if "escalating" in lower or "climbing" in lower:
        return (
            f"Escalating charges at {place}: amounts to this merchant keep climbing over time, "
            f"which can indicate creeping misuse. Review the pattern."
        )
    if "just under" in lower:
        return (
            f"Repeated charges parked just under a category limit at {place}. This can indicate "
            f"deliberate cap-skimming — review whether the spending is being split to stay below the cap."
        )
    if "weekend" in lower:
        return (
            f"This {format_money(amount)} charge at {place} fell on a weekend, outside normal "
            f"business days (severity {weight}/5)."
        )
    if msg:
        return f"Compliance review needed at {place}: {msg}"
    return f"Compliance review needed (severity {weight}/5)."


def _extract_threshold(msg: str, default: float) -> float:
    import re
    m = re.search(r"\$(\d+(?:\.\d+)?)\s*(?:pre-approval|approval)", msg, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"\$(\d+(?:\.\d+)?)", msg)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return default


def _extract_amount_after(msg: str, prefix: str, default: float) -> float:
    import re
    idx = msg.lower().find(prefix.lower())
    if idx >= 0:
        rest = msg[idx + len(prefix):]
        m = re.match(r"(\d+(?:\.\d+)?)", rest)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return default


def format_approval_reason_from_flags(
    flags: list[dict],
    amount: float,
    threshold: float,
    merchant: str | None,
) -> str:
    if flags:
        # Combine EVERY distinct violation (no 3-item cap) so the approver sees the full
        # picture; dedupe identical phrasings to keep the reason readable.
        seen: set[str] = set()
        parts: list[str] = []
        for f in flags:
            msg = _format_flag_message(f, amount, merchant)
            if msg and msg not in seen:
                seen.add(msg)
                parts.append(msg)
        if len(parts) > 1:
            return f"{len(parts)} policy concerns: " + VIOLATION_SEP.join(parts)
        return VIOLATION_SEP.join(parts)
    place = _merchant_label(merchant)
    return (
        f"This {format_money(amount)} charge at {place} exceeds the "
        f"{format_money(threshold)} approval threshold and requires a manager decision."
    )


def format_all_policy_violations(policy_checks: list[dict] | None) -> str:
    """One combined message covering EVERY failed policy check (handles them all)."""
    failed = [c for c in (policy_checks or []) if str(c.get("status")) == "failed"]
    if not failed:
        return ""
    parts: list[str] = []
    for c in failed:
        name = str(c.get("policy_name") or c.get("policy_id") or "Policy").strip()
        msg = str(c.get("message") or "").strip()
        parts.append(f"{name}: {msg}" if msg else name)
    if len(failed) > 1:
        return f"{len(failed)} policies breached — " + VIOLATION_SEP.join(parts)
    return VIOLATION_SEP.join(parts)


def format_deterministic_reco(
    ctx: dict[str, Any],
    threshold: float,
    *,
    deny_weight: int = 4,
) -> tuple[str, str]:
    flags = ctx.get("warnings") or []
    strikes = ctx.get("strike_history")
    budget = ctx.get("budget")
    amount = float(ctx.get("amount_cad") or 0)
    employee = ctx.get("employee") or "Employee"
    department = ctx.get("department") or "Unknown department"
    similar = int((ctx.get("spend_history") or {}).get("similar_prior_count") or 0)

    max_w = max((float(f.get("weight") or 0) for f in flags), default=0.0)
    n_strikes = int(strikes.get("count") or 0) if strikes else 0
    over_budget = bool(budget) and amount > float(budget.get("remaining") or 0)

    if budget:
        budget_txt = (
            f"{department} has {format_money(float(budget['remaining']))} remaining in "
            f"{budget['quarter']} {budget['year']}"
        )
    else:
        budget_txt = "department budget is unavailable"

    base = (
        f"{employee} is requesting {format_money(amount)}. {budget_txt}, with "
        f"{similar} similar expense(s) this year."
    )

    if max_w >= deny_weight or n_strikes >= 2:
        return "deny", (
            f"{base} Deny recommended — high-severity compliance warning "
            f"(max severity {max_w:g}/5) or {n_strikes} prior strike(s) on record."
        )
    if over_budget:
        return "review", (
            f"{base} Review recommended — this request exceeds the remaining department budget."
        )
    if flags:
        return "review", (
            f"{base} Review recommended — {len(flags)} compliance warning(s) "
            f"(max severity {max_w:g}/5)."
        )
    if amount > threshold:
        return "review", (
            f"{base} Review recommended — amount is above the {format_money(threshold)} "
            f"approval threshold with no compliance warnings."
        )
    return "approve", (
        f"{base} Approve recommended — within policy and budget, consistent with past spending."
    )
