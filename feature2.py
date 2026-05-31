"""
Feature 2 — Policy Compliance Engine
====================================
Scans `transactions` against the company expense policy and emits the compliance
artifacts the rest of the platform consumes.  Built to interlock with Feature 4:
this engine *produces* the `transaction_flags` + `employee_strikes` that
`feature4.py` reads when it recommends approve/review/deny.

Design mirrors feature4.py: a deterministic core computes structured "concern"
signals (the things rules can catch — thresholds, splits, duplicates, category
limits), and the LLM only does the *contextual* judgment on the candidates the
core surfaces (a $200 team dinner vs a $200 solo dinner).  Never hard-fails:
any LLM error degrades to a deterministic verdict.

  INPUTS (CSV files mirroring the Supabase tables; only `transactions` required):
    transactions      id, employee_id, date, amount, merchant_name, merchant_category,
                      city, zipcode, latitude, longitude, event_group_id, status  (amount CAD)
    policies          id, effective_date, policy_name, policy_requirements (JSONB), active
                      (optional; built-in defaults if absent. Structured keys in
                      policy_requirements — approval_threshold_cad, category_limits_cad,
                      restricted_categories, restricted_merchants — drive the deterministic
                      checks; any "notes" free text is passed to the LLM.)
    mcc_codes         mcc, edited_description, ...           (optional, for spend categories)
    employees         id, first_name, last_name, department_id   (optional, attribution)
    departments       id, department_name                        (optional)

  OUTPUT (JSON — ready to write back to Supabase):
    {
      "transaction_flags": [ {transaction_id, warning_message, weight} ],              -> INSERT
      "employee_strikes":  [ {employee_id, strike_description, strike_date,
                              amount_cheated} ],                                        -> INSERT
      "notifications":     [ {id, type:"flag", reference_id, message, read} ],          -> INSERT
      "summary": { by_severity, repeat_offenders (ranked), policy }
    }
  weight is an INTEGER 1..5 (transaction_flags.weight CHECK in schema.sql); >= 4 is
  strike-worthy and >= 3 alerts the approver — the scale feature4.py reads.

What it does:
  1. Map MCC -> Brim spend category (so solo vs client meals are distinguishable).
  2. Deterministic detectors: approval-threshold breach, purchase splitting to duck
     the threshold, duplicate charges, per-category limits, round-number anomalies.
  3. LLM scans only the flagged candidates *in context* (policy text + the employee's
     recent spend) and returns a final {is_violation, warning_message, weight}.
  4. Aggregate -> rank violations by severity, surface repeat offenders as strikes.

Usage:
    py feature2.py --transactions transactions.csv --out feature2_output.json
    py feature2.py --transactions transactions.csv --policies policies.csv \
        --employees employees.csv --departments departments.csv --out feature2_output.json
    py feature2.py --transactions transactions.csv --mock-llm        # no API calls
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import defaultdict
from typing import Any

import pandas as pd

# Single source of truth: reuse Feature 4's loaders / category map / LLM factory.
from feature4 import (
    _parse_date,
    build_mcc_category_map,
    load_transactions,
    make_chat_llm,
)


# =========================================================================== #
# Config
# =========================================================================== #

DEFAULT_APPROVAL_THRESHOLD_CAD = 500.0   # purchases at/above this need pre-approval
SPLIT_WINDOW_DAYS = 2                     # charges within this window may be one split purchase
DUPLICATE_WINDOW_DAYS = 1                 # same merchant+amount within this window = likely duplicate
ROUND_NUMBER_MIN_CAD = 100.0             # round-number anomaly only interesting above this
SCAN_BATCH_SIZE = 25                     # candidate transactions per compliance LLM call

# Tunables for the behavioural detectors (velocity / escalation / just-under-limit / geo).
VELOCITY_MIN_SAME_DAY = 4                # >= this many purchases by one employee in one day
ESCALATION_MIN_COUNT = 3                 # >= this many strictly increasing charges to one merchant
JUST_UNDER_MARGIN = 0.10                 # within this fraction below a category limit = "just under"
JUST_UNDER_MIN_COUNT = 2                 # >= this many just-under charges in the same category
GEO_MIN_DISTINCT_CITIES = 2              # distinct cities for one employee on one day = implausible

# Severity weight is an INTEGER 1..5 — the transaction_flags.weight CHECK in schema.sql.
SEV_SPLIT = 5            # split to duck the approval threshold (clear intent)
SEV_RESTRICTED = 4       # restricted merchant / category
SEV_OVER_THRESHOLD = 3   # at/above approval threshold and not approved
SEV_DUPLICATE = 3        # duplicate charge
SEV_GEO = 3              # purchases in 2+ cities same day (physically implausible)
SEV_CATEGORY_LIMIT = 2   # over a per-category soft limit (e.g. solo meal)
SEV_VELOCITY = 2         # unusually many purchases in a single day
SEV_ESCALATION = 2       # steadily climbing charges to the same merchant
SEV_JUST_UNDER = 2       # repeated charges parked just below a category limit
SEV_ROUND = 1            # round-number anomaly (booster; ignored on its own)
SEV_WEEKEND = 1          # weekend transaction (booster; ignored on its own)
HIGH_SEVERITY = 4        # weight >= this = strike-worthy (feature4 leans toward deny)
ALERT_SEVERITY = 3       # weight >= this = notify / email the approver (backend.md)

# Boosters never stand alone: a transaction whose only signals are boosters is dropped.
# geo_anomaly is a booster: with day-granular dates (no time), charges in 2 cities the same
# day are usually legit travel — only meaningful combined with another red flag, not alone.
BOOSTER_CODES = {"round_number", "weekend", "geo_anomaly"}

# Approved statuses -> a threshold breach that's already approved is not a violation.
APPROVED_STATUSES = {"approved", "reimbursed", "closed", "settled"}

# Stable namespace for deterministic incident_id (same pattern as feature4 event groups).
_F2_NS = uuid.UUID("b1115204-0000-4000-8000-000000000002")

# Fallback policy ids when registry lookup misses (seed policies).
CONCERN_DEFAULT_POLICY_ID: dict[str, str] = {
    "over_threshold": "pol-default-approval",
    "split_purchase": "pol-default-approval",
    "just_under_limit": "pol-default-approval",
    "category_limit": "pol-default-meals",
    "restricted_category": "pol-restricted-bars",
    "restricted_merchant": "pol-restricted-bars",
}

# Match concern codes to policy registry traits when seed ids are absent.
CONCERN_POLICY_TRAITS: dict[str, str] = {
    "over_threshold": "has_threshold",
    "split_purchase": "has_threshold",
    "just_under_limit": "has_threshold",
    "category_limit": "has_category_limits",
    "restricted_category": "has_restricted",
    "restricted_merchant": "has_restricted",
}

# Tie-break when multiple concerns share the same weight.
CONCERN_PRIORITY: list[str] = [
    "split_purchase",
    "restricted_category",
    "restricted_merchant",
    "over_threshold",
    "duplicate_charge",
    "geo_anomaly",
    "category_limit",
    "just_under_limit",
    "velocity",
    "escalation",
    "round_number",
    "weekend",
]


# =========================================================================== #
# Policy (structured defaults + free-text for the LLM)
# =========================================================================== #

DEFAULT_POLICY: dict[str, Any] = {
    "policy_name": "Default SMB Expense Policy",
    "approval_threshold_cad": DEFAULT_APPROVAL_THRESHOLD_CAD,
    # per-transaction soft limits by Brim category (the solo-vs-team meal distinction)
    "category_limits_cad": {
        "Repas Personnel": 75.0,    # solo meal
        "Repas Client": 250.0,      # client / team meal
    },
    "restricted_categories": [],            # categories never allowed on the card
    "restricted_merchants": [],             # case-insensitive substrings
    "requirements_text": (
        "Purchases of $500 CAD or more require manager pre-approval. Solo meals "
        "(Repas Personnel) should not exceed $75; client/team meals (Repas Client) "
        "should not exceed $250. Splitting a purchase into multiple smaller charges to "
        "stay under the approval threshold is prohibited. Duplicate charges and personal "
        "expenses on the corporate card are not allowed."
    ),
}


def _parse_requirements(raw: Any) -> dict:
    """`policies.policy_requirements` is JSONB. Accept a dict, a JSON string, or free text.

    Recognized structured keys: approval_threshold_cad, category_limits_cad,
    restricted_categories, restricted_merchants, notes. Anything unparseable is treated
    as free-text `notes` and handed to the LLM."""
    if isinstance(raw, dict):
        return dict(raw)
    s = str(raw).strip()
    if not s:
        return {}
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else {"notes": s}
    except (json.JSONDecodeError, ValueError):
        return {"notes": s}


def load_policy(path: str | None) -> dict[str, Any]:
    """Merge built-in defaults with the active rows of the Supabase `policies` table
    (CSV mirror for batch runs). Structured keys in the JSONB `policy_requirements` drive
    the deterministic thresholds; free-text notes are passed to the LLM for context."""
    policy = {
        **DEFAULT_POLICY,
        "category_limits_cad": dict(DEFAULT_POLICY["category_limits_cad"]),
        "restricted_categories": list(DEFAULT_POLICY["restricted_categories"]),
        "restricted_merchants": list(DEFAULT_POLICY["restricted_merchants"]),
        "policy_registry": {},
        "default_policy_id": None,
    }
    if not path:
        return policy

    df = pd.read_csv(path, encoding="utf-8-sig").fillna("")
    names: list[str] = []
    notes: list[str] = []
    thresholds: list[float] = []
    registry: dict[str, dict] = {}
    default_policy_id: str | None = None
    for _, row in df.iterrows():
        if "active" in df.columns and str(row.get("active")).strip().lower() in ("false", "0", "no", "f"):
            continue
        policy_id = str(row.get("id", "")).strip() or None
        name = str(row.get("policy_name", "")).strip()
        if name:
            names.append(name)
        rules = _parse_requirements(row.get("policy_requirements", ""))
        if policy_id:
            if default_policy_id is None:
                default_policy_id = policy_id
            registry[policy_id] = {
                "policy_name": name or policy_id,
                "has_threshold": rules.get("approval_threshold_cad") is not None,
                "has_category_limits": bool(rules.get("category_limits_cad")),
                "has_restricted": bool(rules.get("restricted_categories") or rules.get("restricted_merchants")),
            }
        if rules.get("approval_threshold_cad") is not None:
            try:
                thresholds.append(float(rules["approval_threshold_cad"]))
            except (TypeError, ValueError):
                pass
        for k, v in (rules.get("category_limits_cad") or {}).items():
            try:
                policy["category_limits_cad"][str(k)] = float(v)
            except (TypeError, ValueError):
                pass
        policy["restricted_categories"].extend(str(c) for c in (rules.get("restricted_categories") or []))
        policy["restricted_merchants"].extend(str(m) for m in (rules.get("restricted_merchants") or []))
        if rules.get("notes"):
            notes.append(str(rules["notes"]))

    if thresholds:
        policy["approval_threshold_cad"] = min(thresholds)   # tightest active threshold wins
    if names:
        policy["policy_name"] = names[0] if len(names) == 1 else f"{len(names)} active policies"
    policy["requirements_text"] = "  ".join(notes) if notes else json.dumps({
        "approval_threshold_cad": policy["approval_threshold_cad"],
        "category_limits_cad": policy["category_limits_cad"],
        "restricted_categories": policy["restricted_categories"],
        "restricted_merchants": policy["restricted_merchants"],
    }, ensure_ascii=False)
    policy["policy_registry"] = registry
    policy["default_policy_id"] = default_policy_id
    return policy


# =========================================================================== #
# Deterministic concern detectors  (concern = {code, message, weight, amount_at_risk})
# =========================================================================== #

def _norm_merchant(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower() if value is not None else ""


def _is_round(amount: float) -> bool:
    return amount >= ROUND_NUMBER_MIN_CAD and abs(amount - round(amount / 50.0) * 50.0) < 0.01


def detect_splits(df: pd.DataFrame, threshold: float, window_days: int) -> dict[str, list[dict]]:
    """Charges to the same merchant by one employee, each < threshold but summing >= threshold
    within a short window -> classic threshold-circumvention split."""
    out: dict[str, list[dict]] = defaultdict(list)
    work = df.assign(_d=df["date"].map(_parse_date), _m=df["merchant_name"].map(_norm_merchant))
    for (_emp, _m), g in work.groupby([work["employee_id"].astype(str), "_m"], dropna=False):
        items = [(str(r["id"]), r["_d"], float(r["amount"])) for _, r in g.iterrows() if r["_d"] is not None]
        items.sort(key=lambda x: x[1])
        i = 0
        while i < len(items):
            j = i + 1
            while j < len(items) and (items[j][1] - items[i][1]).days <= window_days:
                j += 1
            window = items[i:j]
            amounts = [a for _, _, a in window]
            if len(window) >= 2 and all(a < threshold for a in amounts) and sum(amounts) >= threshold:
                total = round(sum(amounts), 2)
                for tid, _, _ in window:
                    out[tid].append({
                        "code": "split_purchase",
                        "message": (f"Possible split: {len(window)} charges totaling ${total:.2f} to the "
                                    f"same merchant within {window_days} day(s), each under the "
                                    f"${threshold:.0f} approval threshold."),
                        "weight": SEV_SPLIT,
                        "amount_at_risk": total,
                    })
                i = j
            else:
                i += 1
    return out


def detect_duplicates(df: pd.DataFrame, window_days: int) -> dict[str, list[dict]]:
    """Same employee + merchant + amount within a day or two -> likely duplicate charge."""
    out: dict[str, list[dict]] = defaultdict(list)
    work = df.assign(_d=df["date"].map(_parse_date), _m=df["merchant_name"].map(_norm_merchant))
    for (_emp, _m, _amt), g in work.groupby(
            [work["employee_id"].astype(str), "_m", work["amount"].round(2)], dropna=False):
        items = [(str(r["id"]), r["_d"]) for _, r in g.iterrows() if r["_d"] is not None]
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x[1])
        for k in range(1, len(items)):
            if (items[k][1] - items[k - 1][1]).days <= window_days:
                for tid, _ in (items[k - 1], items[k]):
                    out[tid].append({
                        "code": "duplicate_charge",
                        "message": f"Possible duplicate: identical ${float(_amt):.2f} charge to the "
                                   f"same merchant within {window_days} day(s).",
                        "weight": SEV_DUPLICATE,
                        "amount_at_risk": round(float(_amt), 2),
                    })
    return out


def _with_day(df: pd.DataFrame) -> pd.DataFrame:
    """Attach parsed datetime (_d) and calendar day (_day); drop unparseable dates."""
    work = df.assign(_d=df["date"].map(_parse_date))
    work = work[work["_d"].notna()].copy()
    work["_day"] = work["_d"].map(lambda d: d.date())
    return work


def detect_velocity(df: pd.DataFrame, min_count: int) -> dict[str, list[dict]]:
    """An employee racking up many purchases in a single calendar day — unusual activity."""
    out: dict[str, list[dict]] = defaultdict(list)
    work = _with_day(df)
    for (_emp, _day), g in work.groupby([work["employee_id"].astype(str), "_day"]):
        if len(g) < min_count:
            continue
        total = round(float(g["amount"].sum()), 2)
        n = len(g)
        for _, r in g.iterrows():
            out[str(r["id"])].append({
                "code": "velocity",
                "message": (f"High purchase velocity: {n} separate charges totaling ${total:.2f} by the "
                            f"same employee on {_day} — unusually concentrated activity."),
                "weight": SEV_VELOCITY,
                "amount_at_risk": round(float(r["amount"]), 2),
            })
    return out


def detect_geo_anomaly(df: pd.DataFrame, min_cities: int) -> dict[str, list[dict]]:
    """Same employee charging in 2+ distinct cities on one day — physically implausible travel."""
    out: dict[str, list[dict]] = defaultdict(list)
    if "city" not in df.columns:
        return out
    work = _with_day(df)
    for (_emp, _day), g in work.groupby([work["employee_id"].astype(str), "_day"]):
        cities = sorted({str(c).strip() for c in g["city"].tolist() if str(c).strip()})
        if len(cities) < min_cities:
            continue
        joined = ", ".join(cities)
        for _, r in g.iterrows():
            out[str(r["id"])].append({
                "code": "geo_anomaly",
                "message": (f"Geographic anomaly: charges in {len(cities)} different cities ({joined}) by "
                            f"the same employee on {_day} — physically implausible in one day."),
                "weight": SEV_GEO,
                "amount_at_risk": round(float(r["amount"]), 2),
            })
    return out


def detect_escalating_merchant(df: pd.DataFrame, min_count: int) -> dict[str, list[dict]]:
    """A run of strictly increasing charges to the same merchant — creeping abuse pattern."""
    out: dict[str, list[dict]] = defaultdict(list)
    work = df.assign(_d=df["date"].map(_parse_date), _m=df["merchant_name"].map(_norm_merchant))
    for (_emp, _m), g in work.groupby([work["employee_id"].astype(str), "_m"], dropna=False):
        items = [(str(r["id"]), r["_d"], float(r["amount"])) for _, r in g.iterrows() if r["_d"] is not None]
        if len(items) < min_count:
            continue
        items.sort(key=lambda x: x[1])
        display = next((str(r["merchant_name"]) for _, r in g.iterrows()
                        if str(r.get("merchant_name") or "").strip()), _m)
        # longest run of strictly increasing amounts in chronological order
        run = [items[0]]
        best: list[tuple] = []
        for cur in items[1:]:
            if cur[2] > run[-1][2]:
                run.append(cur)
            else:
                best = run if len(run) > len(best) else best
                run = [cur]
        best = run if len(run) > len(best) else best
        if len(best) < min_count:
            continue
        first_amt, last_amt = best[0][2], best[-1][2]
        for tid, _, amt in best:
            out[tid].append({
                "code": "escalation",
                "message": (f"Escalating charges at {display}: {len(best)} successive amounts climbing "
                            f"from ${first_amt:.2f} to ${last_amt:.2f}."),
                "weight": SEV_ESCALATION,
                "amount_at_risk": round(last_amt - first_amt, 2),
            })
    return out


def detect_just_under_limit(
    df: pd.DataFrame, policy: dict, margin: float, min_count: int,
) -> dict[str, list[dict]]:
    """Repeated charges parked just below a category limit — deliberate cap-skimming."""
    out: dict[str, list[dict]] = defaultdict(list)
    limits = policy.get("category_limits_cad") or {}
    if not limits or "brim_category" not in df.columns:
        return out
    for (_emp, _cat), g in df.groupby(
            [df["employee_id"].astype(str), df["brim_category"].astype(str)], dropna=False):
        raw_limit = limits.get(_cat)
        if raw_limit is None:
            continue
        try:
            limit = float(raw_limit)
        except (TypeError, ValueError):
            continue
        lower = limit * (1.0 - margin)
        hits = [(str(r["id"]), float(r["amount"])) for _, r in g.iterrows()
                if lower <= float(r["amount"]) < limit]
        if len(hits) < min_count:
            continue
        for tid, amt in hits:
            out[tid].append({
                "code": "just_under_limit",
                "message": (f"Repeated charges just under the ${limit:.0f} {_cat} limit: {len(hits)} "
                            f"charges within {int(margin * 100)}% of the cap (e.g. ${amt:.2f})."),
                "weight": SEV_JUST_UNDER,
                "amount_at_risk": round(amt, 2),
            })
    return out


def detect_row_concerns(row: pd.Series, policy: dict) -> list[dict]:
    """Per-transaction rule checks: threshold, category limit, restricted, round-number, weekend."""
    concerns: list[dict] = []
    amount = float(row["amount"])
    category = str(row.get("brim_category") or "")
    merchant = _norm_merchant(row.get("merchant_name"))
    status = str(row.get("status") or "").strip().lower()
    threshold = policy["approval_threshold_cad"]

    if amount >= threshold and status not in APPROVED_STATUSES:
        concerns.append({
            "code": "over_threshold",
            "message": f"${amount:.2f} is at/above the ${threshold:.0f} pre-approval threshold "
                       f"and is not marked approved (status='{status or 'n/a'}').",
            "weight": SEV_OVER_THRESHOLD,
            "amount_at_risk": round(amount, 2),
        })

    limit = policy["category_limits_cad"].get(category)
    if limit is not None and amount > limit:
        kind = "solo meal" if category == "Repas Personnel" else category
        concerns.append({
            "code": "category_limit",
            "message": f"${amount:.2f} exceeds the ${limit:.0f} limit for {kind} ({category}).",
            "weight": SEV_CATEGORY_LIMIT,
            "amount_at_risk": round(amount - limit, 2),
        })

    if category and category in policy["restricted_categories"]:
        concerns.append({
            "code": "restricted_category",
            "message": f"Category '{category}' is restricted under the expense policy.",
            "weight": SEV_RESTRICTED,
            "amount_at_risk": round(amount, 2),
        })
    if any(rm and rm in merchant for rm in (m.lower() for m in policy["restricted_merchants"])):
        concerns.append({
            "code": "restricted_merchant",
            "message": f"Merchant '{row.get('merchant_name')}' is on the restricted list.",
            "weight": SEV_RESTRICTED,
            "amount_at_risk": round(amount, 2),
        })

    if _is_round(amount):
        concerns.append({
            "code": "round_number",
            "message": f"Round-number amount (${amount:.2f}) — weak anomaly signal.",
            "weight": SEV_ROUND,
            "amount_at_risk": round(amount, 2),
        })

    d = _parse_date(row.get("date"))
    if d is not None and d.weekday() >= 5:
        concerns.append({
            "code": "weekend",
            "message": (f"Weekend transaction (dated {str(row.get('date'))[:10]}) — outside normal "
                        f"business days."),
            "weight": SEV_WEEKEND,
            "amount_at_risk": round(amount, 2),
        })
    return concerns


def compute_concerns(df: pd.DataFrame, policy: dict) -> dict[str, list[dict]]:
    """All detectors merged into {transaction_id: [concern, ...]}."""
    concerns: dict[str, list[dict]] = defaultdict(list)
    for tid, cs in detect_splits(df, policy["approval_threshold_cad"], SPLIT_WINDOW_DAYS).items():
        concerns[tid].extend(cs)
    for tid, cs in detect_duplicates(df, DUPLICATE_WINDOW_DAYS).items():
        concerns[tid].extend(cs)
    for tid, cs in detect_velocity(df, VELOCITY_MIN_SAME_DAY).items():
        concerns[tid].extend(cs)
    for tid, cs in detect_geo_anomaly(df, GEO_MIN_DISTINCT_CITIES).items():
        concerns[tid].extend(cs)
    for tid, cs in detect_escalating_merchant(df, ESCALATION_MIN_COUNT).items():
        concerns[tid].extend(cs)
    for tid, cs in detect_just_under_limit(df, policy, JUST_UNDER_MARGIN, JUST_UNDER_MIN_COUNT).items():
        concerns[tid].extend(cs)
    for _, row in df.iterrows():
        cs = detect_row_concerns(row, policy)
        if cs:
            concerns[str(row["id"])].extend(cs)
    # boosters (round-number, weekend) never stand alone -> drop if they're the only signal
    for tid in list(concerns):
        if concerns[tid] and all(c["code"] in BOOSTER_CODES for c in concerns[tid]):
            del concerns[tid]
    return concerns


# =========================================================================== #
# Incident groups — one flag per multi-transaction detector group
# =========================================================================== #

ROW_LEVEL_CODES = {
    "over_threshold",
    "category_limit",
    "restricted_category",
    "restricted_merchant",
    "round_number",
    "weekend",
}


def _incident_id_for(code: str, transaction_ids: list[str]) -> str:
    key = f"{code}|" + "|".join(sorted(str(t) for t in transaction_ids))
    return uuid.uuid5(_F2_NS, key).hex


def _priority_rank(code: str) -> int:
    try:
        return CONCERN_PRIORITY.index(code)
    except ValueError:
        return len(CONCERN_PRIORITY)


def _primary_transaction_id(df: pd.DataFrame, transaction_ids: list[str]) -> str:
    by_id = {str(r["id"]): r for _, r in df.iterrows()}
    ordered = sorted(
        transaction_ids,
        key=lambda tid: (
            _parse_date(by_id[tid].get("date")) or pd.Timestamp.min,
            tid,
        ),
    )
    return ordered[0]


def _registry_policy_for_concern(code: str, registry: dict[str, dict]) -> str | None:
    trait = CONCERN_POLICY_TRAITS.get(code)
    if not trait:
        return None
    for policy_id, meta in registry.items():
        if meta.get(trait):
            return policy_id
    return None


def resolve_policy_id(concerns: list[dict], policy: dict) -> str | None:
    """Pick the policy_id for an incident from its concerns."""
    registry: dict[str, dict] = policy.get("policy_registry") or {}
    if not concerns:
        return policy.get("default_policy_id")
    ranked = sorted(
        concerns,
        key=lambda c: (-int(c["weight"]), _priority_rank(str(c["code"]))),
    )
    for c in ranked:
        code = str(c["code"])
        default_id = CONCERN_DEFAULT_POLICY_ID.get(code)
        if default_id and default_id in registry:
            return default_id
        matched = _registry_policy_for_concern(code, registry)
        if matched:
            return matched
    if policy.get("default_policy_id"):
        return policy["default_policy_id"]
    if registry:
        return next(iter(registry))
    return None


def _collect_split_incidents(
    df: pd.DataFrame, threshold: float, window_days: int,
) -> list[dict]:
    incidents: list[dict] = []
    work = df.assign(_d=df["date"].map(_parse_date), _m=df["merchant_name"].map(_norm_merchant))
    for (_emp, _m), g in work.groupby([work["employee_id"].astype(str), "_m"], dropna=False):
        items = [(str(r["id"]), r["_d"], float(r["amount"])) for _, r in g.iterrows() if r["_d"] is not None]
        items.sort(key=lambda x: x[1])
        i = 0
        while i < len(items):
            j = i + 1
            while j < len(items) and (items[j][1] - items[i][1]).days <= window_days:
                j += 1
            window = items[i:j]
            amounts = [a for _, _, a in window]
            if len(window) >= 2 and all(a < threshold for a in amounts) and sum(amounts) >= threshold:
                total = round(sum(amounts), 2)
                tids = [tid for tid, _, _ in window]
                concern = {
                    "code": "split_purchase",
                    "message": (f"Possible split: {len(window)} charges totaling ${total:.2f} to the "
                                f"same merchant within {window_days} day(s), each under the "
                                f"${threshold:.0f} approval threshold."),
                    "weight": SEV_SPLIT,
                    "amount_at_risk": total,
                }
                incidents.append({
                    "incident_id": _incident_id_for("split_purchase", tids),
                    "transaction_ids": tids,
                    "concern_code": "split_purchase",
                    "concerns": [concern],
                })
                i = j
            else:
                i += 1
    return incidents


def _collect_duplicate_incidents(df: pd.DataFrame, window_days: int) -> list[dict]:
    incidents: list[dict] = []
    seen: set[str] = set()
    work = df.assign(_d=df["date"].map(_parse_date), _m=df["merchant_name"].map(_norm_merchant))
    for (_emp, _m, _amt), g in work.groupby(
            [work["employee_id"].astype(str), "_m", work["amount"].round(2)], dropna=False):
        items = [(str(r["id"]), r["_d"]) for _, r in g.iterrows() if r["_d"] is not None]
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x[1])
        for k in range(1, len(items)):
            if (items[k][1] - items[k - 1][1]).days <= window_days:
                tids = sorted([items[k - 1][0], items[k][0]])
                iid = _incident_id_for("duplicate_charge", tids)
                if iid in seen:
                    continue
                seen.add(iid)
                concern = {
                    "code": "duplicate_charge",
                    "message": f"Possible duplicate: identical ${float(_amt):.2f} charge to the "
                               f"same merchant within {window_days} day(s).",
                    "weight": SEV_DUPLICATE,
                    "amount_at_risk": round(float(_amt), 2),
                }
                incidents.append({
                    "incident_id": iid,
                    "transaction_ids": tids,
                    "concern_code": "duplicate_charge",
                    "concerns": [concern],
                })
    return incidents


def _collect_velocity_incidents(df: pd.DataFrame, min_count: int) -> list[dict]:
    incidents: list[dict] = []
    work = _with_day(df)
    for (_emp, _day), g in work.groupby([work["employee_id"].astype(str), "_day"]):
        if len(g) < min_count:
            continue
        total = round(float(g["amount"].sum()), 2)
        n = len(g)
        tids = [str(r["id"]) for _, r in g.iterrows()]
        concern = {
            "code": "velocity",
            "message": (f"High purchase velocity: {n} separate charges totaling ${total:.2f} by the "
                        f"same employee on {_day} — unusually concentrated activity."),
            "weight": SEV_VELOCITY,
            "amount_at_risk": total,
        }
        incidents.append({
            "incident_id": _incident_id_for("velocity", tids),
            "transaction_ids": tids,
            "concern_code": "velocity",
            "concerns": [concern],
        })
    return incidents


def _collect_geo_incidents(df: pd.DataFrame, min_cities: int) -> list[dict]:
    incidents: list[dict] = []
    if "city" not in df.columns:
        return incidents
    work = _with_day(df)
    for (_emp, _day), g in work.groupby([work["employee_id"].astype(str), "_day"]):
        cities = sorted({str(c).strip() for c in g["city"].tolist() if str(c).strip()})
        if len(cities) < min_cities:
            continue
        joined = ", ".join(cities)
        tids = [str(r["id"]) for _, r in g.iterrows()]
        concern = {
            "code": "geo_anomaly",
            "message": (f"Geographic anomaly: charges in {len(cities)} different cities ({joined}) by "
                        f"the same employee on {_day} — physically implausible in one day."),
            "weight": SEV_GEO,
            "amount_at_risk": round(float(g["amount"].sum()), 2),
        }
        incidents.append({
            "incident_id": _incident_id_for("geo_anomaly", tids),
            "transaction_ids": tids,
            "concern_code": "geo_anomaly",
            "concerns": [concern],
        })
    return incidents


def _collect_escalation_incidents(df: pd.DataFrame, min_count: int) -> list[dict]:
    incidents: list[dict] = []
    work = df.assign(_d=df["date"].map(_parse_date), _m=df["merchant_name"].map(_norm_merchant))
    for (_emp, _m), g in work.groupby([work["employee_id"].astype(str), "_m"], dropna=False):
        items = [(str(r["id"]), r["_d"], float(r["amount"])) for _, r in g.iterrows() if r["_d"] is not None]
        if len(items) < min_count:
            continue
        items.sort(key=lambda x: x[1])
        display = next((str(r["merchant_name"]) for _, r in g.iterrows()
                        if str(r.get("merchant_name") or "").strip()), _m)
        run = [items[0]]
        best: list[tuple] = []
        for cur in items[1:]:
            if cur[2] > run[-1][2]:
                run.append(cur)
            else:
                best = run if len(run) > len(best) else best
                run = [cur]
        best = run if len(run) > len(best) else best
        if len(best) < min_count:
            continue
        first_amt, last_amt = best[0][2], best[-1][2]
        tids = [tid for tid, _, _ in best]
        concern = {
            "code": "escalation",
            "message": (f"Escalating charges at {display}: {len(best)} successive amounts climbing "
                        f"from ${first_amt:.2f} to ${last_amt:.2f}."),
            "weight": SEV_ESCALATION,
            "amount_at_risk": round(last_amt - first_amt, 2),
        }
        incidents.append({
            "incident_id": _incident_id_for("escalation", tids),
            "transaction_ids": tids,
            "concern_code": "escalation",
            "concerns": [concern],
        })
    return incidents


def _collect_just_under_incidents(
    df: pd.DataFrame, policy: dict, margin: float, min_count: int,
) -> list[dict]:
    incidents: list[dict] = []
    limits = policy.get("category_limits_cad") or {}
    if not limits or "brim_category" not in df.columns:
        return incidents
    for (_emp, _cat), g in df.groupby(
            [df["employee_id"].astype(str), df["brim_category"].astype(str)], dropna=False):
        raw_limit = limits.get(_cat)
        if raw_limit is None:
            continue
        try:
            limit = float(raw_limit)
        except (TypeError, ValueError):
            continue
        lower = limit * (1.0 - margin)
        hits = [(str(r["id"]), float(r["amount"])) for _, r in g.iterrows()
                if lower <= float(r["amount"]) < limit]
        if len(hits) < min_count:
            continue
        tids = [tid for tid, _ in hits]
        concern = {
            "code": "just_under_limit",
            "message": (f"Repeated charges just under the ${limit:.0f} {_cat} limit: {len(hits)} "
                        f"charges within {int(margin * 100)}% of the cap."),
            "weight": SEV_JUST_UNDER,
            "amount_at_risk": round(sum(a for _, a in hits), 2),
        }
        incidents.append({
            "incident_id": _incident_id_for("just_under_limit", tids),
            "transaction_ids": tids,
            "concern_code": "just_under_limit",
            "concerns": [concern],
        })
    return incidents


def _collect_row_incidents(
    df: pd.DataFrame, policy: dict, concerns: dict[str, list[dict]],
) -> list[dict]:
    incidents: list[dict] = []
    for tid, cs in concerns.items():
        for c in cs:
            if c["code"] not in ROW_LEVEL_CODES:
                continue
            incidents.append({
                "incident_id": _incident_id_for(str(c["code"]), [tid]),
                "transaction_ids": [tid],
                "concern_code": str(c["code"]),
                "concerns": [c],
            })
    return incidents


def compute_incident_groups(
    df: pd.DataFrame, policy: dict, concerns: dict[str, list[dict]],
) -> list[dict]:
    """Build one incident per detector group; row-level codes stay per (code, transaction)."""
    incidents: list[dict] = []
    threshold = policy["approval_threshold_cad"]
    incidents.extend(_collect_split_incidents(df, threshold, SPLIT_WINDOW_DAYS))
    incidents.extend(_collect_duplicate_incidents(df, DUPLICATE_WINDOW_DAYS))
    incidents.extend(_collect_velocity_incidents(df, VELOCITY_MIN_SAME_DAY))
    incidents.extend(_collect_geo_incidents(df, GEO_MIN_DISTINCT_CITIES))
    incidents.extend(_collect_escalation_incidents(df, ESCALATION_MIN_COUNT))
    incidents.extend(_collect_just_under_incidents(
        df, policy, JUST_UNDER_MARGIN, JUST_UNDER_MIN_COUNT,
    ))
    incidents.extend(_collect_row_incidents(df, policy, concerns))

    for inc in incidents:
        inc["policy_id"] = resolve_policy_id(inc["concerns"], policy)
    return incidents


def build_employee_context(df: pd.DataFrame, candidates_by_emp: dict[str, int]) -> dict[str, dict]:
    ctx: dict[str, dict] = {}
    for emp, g in df.groupby(df["employee_id"].astype(str)):
        cats = {k: round(v, 2) for k, v in g.groupby("brim_category")["amount"].sum().items()}
        name = g["employee_name"].dropna().iloc[0] if g["employee_name"].notna().any() else None
        dept = g["department"].dropna().iloc[0] if g["department"].notna().any() else None
        ctx[emp] = {
            "name": name, "department": dept,
            "txn_count": int(len(g)),
            "total_spend_cad": round(float(g["amount"].sum()), 2),
            "category_breakdown_cad": cats,
            "flagged_so_far": int(candidates_by_emp.get(emp, 0)),
        }
    return ctx


# =========================================================================== #
# Compliance verdicts: LLM in context, deterministic fallback
# =========================================================================== #

def _verdict_schema():
    from pydantic import BaseModel, Field

    class Verdict(BaseModel):
        transaction_id: str
        is_violation: bool = Field(description="true if this transaction violates the policy")
        warning_message: str = Field(description="specific, references amounts/merchant/category/pattern")
        weight: int = Field(description="integer severity 1..5 (5=clear/intentional, 3=needs review, 1=weak)")
        policy: str = Field(description="which rule it breaches, or 'compliant'")

    class Batch(BaseModel):
        verdicts: list[Verdict]

    return Batch


SCAN_SYSTEM = """You are a corporate expense-policy compliance officer.
Each item is one transaction the deterministic engine already flagged as a candidate:
you get the active policy text, the transaction, the concern signals the engine
computed, and the employee's recent spend context. Decide whether it actually violates
policy and reason IN CONTEXT.

Patterns to weigh (the engine surfaces these as concern codes — combine them, don't pick one):
- over_threshold: at/above the pre-approval threshold and not approved.
- split_purchase: several charges to one merchant just under the threshold = dodging approval.
- duplicate_charge: identical repeated charges to the same merchant.
- category_limit / just_under_limit: over a per-category cap, or repeatedly parked just below it.
- restricted_category / restricted_merchant: spend the policy forbids outright.
- velocity: many purchases by one employee in a single day.
- geo_anomaly: charges in 2+ cities the same day — physically implausible travel.
- escalation: charges to one merchant that keep climbing over time.
- round_number / weekend: weak boosters; meaningful only alongside another signal.
Also watch for personal spend on the corporate card and a client/team meal vs a solo meal.

If MULTIPLE patterns apply to one transaction, the warning_message MUST mention ALL of
them in one sentence (e.g. "$520 over the $500 threshold AND 4th charge that day"), and
set the weight to the most severe.
Assign an INTEGER severity weight 1..5 (5 = clear/intentional violation, 4 = serious,
3 = needs approver review, 2 = soft-limit breach, 1 = weak signal); >=4 is strike-worthy.
Reference the actual numbers, merchant, category, threshold, and any pattern. If on
reflection it is fine, return is_violation=false. Be concise."""

SCAN_HUMAN = """Active policy: {policy_name}
Policy requirements: {requirements}

Candidate transactions (JSON array). Return one verdict per item, echoing transaction_id.

{candidates_json}

Judge all {n}."""


def _fallback_verdict(tid: str, concerns: list[dict], policy_name: str) -> dict:
    weight = max(1, min(5, max(int(c["weight"]) for c in concerns)))
    return {
        "transaction_id": tid,
        "is_violation": True,
        "warning_message": "; ".join(c["message"] for c in concerns),
        "weight": weight,
        "policy": policy_name,
    }


def scan(df: pd.DataFrame, concerns: dict[str, list[dict]], policy: dict,
         emp_ctx: dict[str, dict], use_llm: bool) -> dict[str, dict]:
    """Return {transaction_id: verdict} for every candidate (transaction with concerns)."""
    by_id = {str(r["id"]): r for _, r in df.iterrows()}
    candidate_ids = [tid for tid, cs in concerns.items() if cs]
    verdicts: dict[str, dict] = {}

    if not candidate_ids:
        return verdicts

    if use_llm:
        from langchain_core.prompts import ChatPromptTemplate
        chain = ChatPromptTemplate.from_messages(
            [("system", SCAN_SYSTEM), ("human", SCAN_HUMAN)]
        ) | make_chat_llm().with_structured_output(_verdict_schema())

        for start in range(0, len(candidate_ids), SCAN_BATCH_SIZE):
            batch = candidate_ids[start:start + SCAN_BATCH_SIZE]
            payload = []
            for tid in batch:
                r = by_id[tid]
                emp = str(r["employee_id"])
                payload.append({
                    "transaction_id": tid,
                    "employee_id": emp,
                    "amount_cad": round(float(r["amount"]), 2),
                    "merchant": r.get("merchant_name"),
                    "category": r.get("brim_category"),
                    "city": r.get("city"),
                    "date": str(r.get("date"))[:10],
                    "concerns": [{"code": c["code"], "detail": c["message"]} for c in concerns[tid]],
                    "employee_context": emp_ctx.get(emp, {}),
                })
            res = chain.invoke({
                "policy_name": policy["policy_name"],
                "requirements": policy["requirements_text"],
                "candidates_json": json.dumps(payload, ensure_ascii=False),
                "n": len(batch),
            })
            for v in res.verdicts:
                if v.transaction_id in concerns:
                    verdicts[v.transaction_id] = {
                        "transaction_id": v.transaction_id,
                        "is_violation": bool(v.is_violation),
                        "warning_message": v.warning_message,
                        "weight": max(1, min(5, int(round(float(v.weight))))),
                        "policy": v.policy,
                    }
        # any candidate the model dropped -> deterministic fallback
        for tid in candidate_ids:
            verdicts.setdefault(tid, _fallback_verdict(tid, concerns[tid], policy["policy_name"]))
    else:
        for tid in candidate_ids:
            verdicts[tid] = _fallback_verdict(tid, concerns[tid], policy["policy_name"])

    return verdicts


# =========================================================================== #
# Assemble outputs: transaction_flags, employee_strikes, notifications, summary
# =========================================================================== #

def _severity_band(w: int) -> str:
    return "high" if w >= HIGH_SEVERITY else ("medium" if w >= 2 else "low")


def build_outputs(
    df: pd.DataFrame,
    verdicts: dict[str, dict],
    policy: dict,
    incidents: list[dict],
) -> dict:
    by_id = {str(r["id"]): r for _, r in df.iterrows()}
    flags: list[dict] = []
    strikes: list[dict] = []
    notifications: list[dict] = []
    offenders: dict[str, dict] = defaultdict(lambda: {"flag_count": 0, "amount_cheated": 0.0, "max_weight": 0.0})
    seen_incidents: set[str] = set()

    for inc in incidents:
        iid = str(inc["incident_id"])
        if iid in seen_incidents:
            continue
        seen_incidents.add(iid)

        tids = [str(t) for t in inc["transaction_ids"]]
        group_verdicts = [verdicts[t] for t in tids if t in verdicts and verdicts[t].get("is_violation")]
        if not group_verdicts:
            continue

        weight = max(int(v["weight"]) for v in group_verdicts)
        concern_msgs = list(dict.fromkeys(c["message"] for c in inc["concerns"]))
        primary_tid = _primary_transaction_id(df, tids)
        primary_v = verdicts.get(primary_tid)
        if primary_v and primary_v.get("is_violation"):
            pv = str(primary_v.get("warning_message", "")).strip()
            warning_message = pv if pv else "; ".join(concern_msgs)
        else:
            warning_message = "; ".join(concern_msgs)

        related = sorted(tids, key=lambda tid: (
            _parse_date(by_id[tid].get("date")) or pd.Timestamp.min,
            tid,
        ))
        band = _severity_band(weight)
        policy_id = inc.get("policy_id") or resolve_policy_id(inc["concerns"], policy)

        flags.append({
            "transaction_id": primary_tid,
            "warning_message": warning_message,
            "weight": weight,
            "policy_id": policy_id,
            "incident_id": iid,
            "related_transaction_ids": related,
        })
        notifications.append({
            "id": uuid.uuid4().hex,
            "type": "flag",
            "reference_id": primary_tid,
            "message": f"[{band.upper()}] {warning_message}",
            "read": False,
        })

        for tid in tids:
            if tid not in by_id:
                continue
            r = by_id[tid]
            emp = str(r["employee_id"])
            own_amount = round(float(r["amount"]), 2)
            v = verdicts.get(tid)
            if not v or not v.get("is_violation"):
                continue

            o = offenders[emp]
            if tid == primary_tid:
                o["flag_count"] += 1
            o["amount_cheated"] = round(o["amount_cheated"] + own_amount, 2)
            o["max_weight"] = max(o["max_weight"], int(v["weight"]))

            if int(v["weight"]) >= HIGH_SEVERITY:
                strikes.append({
                    "employee_id": emp,
                    "strike_description": warning_message,
                    "strike_date": str(r.get("date"))[:10] or None,
                    "amount_cheated": own_amount,
                })

    # rank repeat offenders by recidivism then severity then dollars
    ranked = []
    for emp, o in offenders.items():
        r0 = next((by_id[t] for t in by_id if str(by_id[t]["employee_id"]) == emp), None)
        ranked.append({
            "employee_id": emp,
            "employee_name": (r0.get("employee_name") if r0 is not None else None),
            "department": (r0.get("department") if r0 is not None else None),
            "flag_count": o["flag_count"],
            "amount_cheated_cad": o["amount_cheated"],
            "max_weight": round(o["max_weight"], 2),
            "repeat_offender": o["flag_count"] >= 2,
        })
    ranked.sort(key=lambda x: (x["flag_count"], x["max_weight"], x["amount_cheated_cad"]), reverse=True)

    by_sev = {"high": 0, "medium": 0, "low": 0}
    for f in flags:
        by_sev[_severity_band(f["weight"])] += 1

    return {
        "transaction_flags": flags,
        "employee_strikes": strikes,
        "notifications": notifications,
        "summary": {
            "by_severity": by_sev,
            "repeat_offenders": ranked,
            "policy": policy["policy_name"],
        },
    }


# =========================================================================== #
# Runner
# =========================================================================== #

def run(df: pd.DataFrame, policy: dict, use_llm: bool) -> dict:
    concerns = compute_concerns(df, policy)
    incidents = compute_incident_groups(df, policy, concerns)
    candidates_by_emp: dict[str, int] = defaultdict(int)
    id_to_emp = {str(r["id"]): str(r["employee_id"]) for _, r in df.iterrows()}
    for tid, cs in concerns.items():
        if cs:
            candidates_by_emp[id_to_emp.get(tid, "?")] += 1
    emp_ctx = build_employee_context(df, candidates_by_emp)
    verdicts = scan(df, concerns, policy, emp_ctx, use_llm)
    out = build_outputs(df, verdicts, policy, incidents)
    print(f"[scan: {sum(1 for c in concerns.values() if c)} candidates, "
          f"{len(incidents)} incidents, {len(out['transaction_flags'])} flags, "
          f"{len(out['employee_strikes'])} strikes]", file=sys.stderr)
    return out


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Feature 2 — Policy Compliance Engine.")
    ap.add_argument("--transactions", required=True, help="transactions CSV (Supabase shape).")
    ap.add_argument("--policies", default=None, help="policies CSV (optional; built-in defaults otherwise).")
    ap.add_argument("--mcc", default="mcc_codes.csv")
    ap.add_argument("--employees", default=None)
    ap.add_argument("--departments", default=None)
    ap.add_argument("--model", default=None, help="Gemini model id (default gemini-3.1-flash-lite).")
    ap.add_argument("--approval-threshold", type=float, default=None, help="Override the approval threshold (CAD).")
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N transactions.")
    ap.add_argument("--mock-llm", action="store_true", help="No API calls (deterministic verdicts).")
    ap.add_argument("--out", default=None, help="Write JSON here (default stdout).")
    args = ap.parse_args()
    if args.model:
        os.environ["GEMINI_MODEL"] = args.model

    cat_map = build_mcc_category_map(args.mcc)
    df = load_transactions(args.transactions, cat_map, args.employees, args.departments)
    if args.limit is not None and args.limit < len(df):
        df = df.head(args.limit)
        print(f"[limited to first {args.limit} transactions]", file=sys.stderr)

    policy = load_policy(args.policies)
    if args.approval_threshold is not None:
        policy["approval_threshold_cad"] = args.approval_threshold

    use_llm = not args.mock_llm
    try:
        out = run(df, policy, use_llm)
        mode = (os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite") if use_llm else "mock")
    except Exception as exc:  # noqa: BLE001 — never hard-fail; degrade to deterministic
        print(f"[LLM unavailable: {exc}] -> deterministic fallback", file=sys.stderr)
        out = run(df, policy, use_llm=False)
        mode = "mock (fallback)"

    output = {
        "feature": "2 - Policy Compliance Engine",
        "model": mode,
        "transaction_count": int(len(df)),
        "flag_count": len(out["transaction_flags"]),
        **out,
    }
    payload = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"[wrote {len(out['transaction_flags'])} flags + {len(out['employee_strikes'])} strikes "
              f"-> {args.out}]", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
