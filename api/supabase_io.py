"""Supabase fetch/persist helpers shared by API routes and feature CLIs."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from feature2 import DEFAULT_POLICY, _parse_requirements
from api.data_loaders import (
    budgets_from_df,
    enrich_transactions,
    flags_from_df,
    strikes_from_df,
)
from feature4 import (
    DEFAULT_BRIM_CATEGORY,
    _normalize_mcc,
    build_mcc_category_map,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
MCC_CSV = ROOT / "mcc_codes.csv"


def get_supabase_client():
    from supabase import create_client

    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
    return create_client(url, key)


def fetch_table(client, table: str, select: str = "*", page_size: int = 1000) -> pd.DataFrame:
    rows: list[dict] = []
    offset = 0
    while True:
        res = client.table(table).select(select).range(offset, offset + page_size - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_mcc_category_map(client) -> dict[str, str]:
    mcc_df = fetch_table(client, "mcc_codes")
    if not mcc_df.empty and "mcc" in mcc_df.columns:
        from feature4 import _resolve_category

        out: dict[str, str] = {}
        desc_col = "edited_description" if "edited_description" in mcc_df.columns else mcc_df.columns[1]
        for _, row in mcc_df.iterrows():
            mcc = _normalize_mcc(row.get("mcc"))
            if mcc:
                out[mcc] = _resolve_category(mcc, str(row.get(desc_col, "")))
        return out
    if MCC_CSV.is_file():
        return build_mcc_category_map(str(MCC_CSV))
    return {}


def apply_brim_categories(df: pd.DataFrame, cat_map: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    if "merchant_category" not in df.columns:
        df["merchant_category"] = None
    df["_mcc"] = df["merchant_category"].apply(_normalize_mcc)
    df["brim_category"] = df["_mcc"].map(cat_map).fillna(DEFAULT_BRIM_CATEGORY)
    return df


# Card-statement lines that are NOT purchases: balance payments (CWB EFT PAYMENT),
# point redemptions, and account fees (cash-advance / auth-user / interest charges).
# In this dataset they are exactly the rows with no merchant category (MCC '0'/blank) —
# the raw source transaction codes (0108 = EFT payment, 3001 = purchase, …) were not
# loaded into Supabase, but MCC is a faithful proxy. Excluding them stops ~$1.2M of card
# payments from corrupting spend totals, expense reports, compliance scans and budgets.
# Real refunds keep their merchant's MCC (e.g. 5533) and are intentionally retained.
_NON_PURCHASE_MCC = {"", "0", "00", "000", "0000", "00000", "nan", "none", "null"}


def _drop_non_purchase_rows(tx_df: pd.DataFrame) -> pd.DataFrame:
    if "merchant_category" not in tx_df.columns:
        return tx_df
    mcc = (
        tx_df["merchant_category"].astype(str).str.strip()
        .str.replace(r"\.0$", "", regex=True).str.lower()
    )
    return tx_df[~mcc.isin(_NON_PURCHASE_MCC)].copy()


def load_transactions_frame(client) -> pd.DataFrame:
    tx_df = fetch_table(client, "transactions")
    if tx_df.empty:
        raise RuntimeError("No rows in Supabase table `transactions`")
    tx_df = _drop_non_purchase_rows(tx_df)
    emp_df = fetch_table(client, "employees")
    dept_df = fetch_table(client, "departments")
    df = enrich_transactions(
        tx_df,
        emp_df if not emp_df.empty else None,
        dept_df if not dept_df.empty else None,
    )
    cat_map = get_mcc_category_map(client)
    return apply_brim_categories(df, cat_map)


def load_all_from_supabase(client):
    """Returns (df, flags, strikes, budgets) for Feature 3."""
    df = load_transactions_frame(client)
    flags_df = fetch_table(client, "transaction_flags")
    strikes_df = fetch_table(client, "employee_strikes")
    budgets_df = fetch_table(client, "budgets")
    flags = flags_from_df(flags_df) if not flags_df.empty else {}
    strikes = strikes_from_df(strikes_df) if not strikes_df.empty else {}
    budgets = budgets_from_df(budgets_df) if not budgets_df.empty else {}
    return df, flags, strikes, budgets


def load_policy_from_dataframe(policies_df: pd.DataFrame) -> dict[str, Any]:
    """Merge active Supabase policies into the policy dict Feature 2 expects."""
    policy: dict[str, Any] = {
        **DEFAULT_POLICY,
        "category_limits_cad": dict(DEFAULT_POLICY["category_limits_cad"]),
        "restricted_categories": list(DEFAULT_POLICY["restricted_categories"]),
        "restricted_merchants": list(DEFAULT_POLICY["restricted_merchants"]),
    }
    if policies_df.empty:
        return policy

    names: list[str] = []
    notes: list[str] = []
    thresholds: list[float] = []
    for _, row in policies_df.iterrows():
        if "active" in policies_df.columns:
            active_val = str(row.get("active", "")).strip().lower()
            if active_val in ("false", "0", "no", "f"):
                continue
        name = str(row.get("policy_name", "")).strip()
        if name:
            names.append(name)
        rules = _parse_requirements(row.get("policy_requirements", ""))
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
        policy["restricted_categories"].extend(
            str(c) for c in (rules.get("restricted_categories") or [])
        )
        policy["restricted_merchants"].extend(
            str(m) for m in (rules.get("restricted_merchants") or [])
        )
        if rules.get("notes"):
            notes.append(str(rules["notes"]))

    if thresholds:
        policy["approval_threshold_cad"] = min(thresholds)
    if names:
        policy["policy_name"] = names[0] if len(names) == 1 else f"{len(names)} active policies"
    policy["requirements_text"] = "  ".join(notes) if notes else json.dumps(
        {
            "approval_threshold_cad": policy["approval_threshold_cad"],
            "category_limits_cad": policy["category_limits_cad"],
            "restricted_categories": policy["restricted_categories"],
            "restricted_merchants": policy["restricted_merchants"],
        },
        ensure_ascii=False,
    )
    return policy


def load_active_policy(client) -> dict[str, Any]:
    pol_df = fetch_table(client, "policies")
    if not pol_df.empty and "active" in pol_df.columns:
        pol_df = pol_df[
            ~pol_df["active"].astype(str).str.strip().str.lower().isin(("false", "0", "no", "f"))
        ]
    return load_policy_from_dataframe(pol_df)


def flags_dict_from_db(client) -> dict[str, list[dict]]:
    flags_df = fetch_table(client, "transaction_flags")
    return flags_from_df(flags_df) if not flags_df.empty else {}


def strikes_dict_from_db(client) -> dict[str, dict]:
    strikes_df = fetch_table(client, "employee_strikes")
    return strikes_from_df(strikes_df) if not strikes_df.empty else {}


def clear_compliance_artifacts(client, transaction_ids: list[str]) -> dict[str, int]:
    """Remove prior flags and flag notifications for transactions about to be rescanned."""
    if not transaction_ids:
        return {"flags_deleted": 0, "notifications_deleted": 0}

    flags_res = (
        client.table("transaction_flags")
        .delete()
        .in_("transaction_id", transaction_ids)
        .execute()
    )
    flags_deleted = len(flags_res.data or [])

    notif_res = (
        client.table("notifications")
        .delete()
        .eq("type", "flag")
        .in_("reference_id", transaction_ids)
        .execute()
    )
    notifications_deleted = len(notif_res.data or [])

    return {
        "flags_deleted": flags_deleted,
        "notifications_deleted": notifications_deleted,
    }


def persist_compliance_output(
    client,
    output: dict,
    *,
    transaction_ids: list[str] | None = None,
    replace: bool = True,
) -> dict:
    """Insert flags, strikes, notifications; optionally clear prior flags for scanned txs."""
    flags = output.get("transaction_flags") or []
    strikes = output.get("employee_strikes") or []
    notifications = output.get("notifications") or []

    cleared: dict[str, int] = {}
    if replace and transaction_ids:
        cleared = clear_compliance_artifacts(client, transaction_ids)

    inserted_flags = 0
    if flags:
        res = client.table("transaction_flags").insert(flags).execute()
        inserted_flags = len(res.data or [])

    inserted_strikes = 0
    if strikes:
        res = client.table("employee_strikes").insert(strikes).execute()
        inserted_strikes = len(res.data or [])

    inserted_notifications = 0
    if notifications:
        client.table("notifications").upsert(notifications, on_conflict="id").execute()
        inserted_notifications = len(notifications)

    return {
        "flags_deleted": cleared.get("flags_deleted", 0),
        "notifications_deleted": cleared.get("notifications_deleted", 0),
        "flags_inserted": inserted_flags,
        "strikes_inserted": inserted_strikes,
        "notifications_upserted": inserted_notifications,
    }


def persist_pipeline_to_supabase(client, approval_requests: list[dict], notifications: list[dict]) -> None:
    reqs = [{k: v for k, v in r.items() if not k.startswith("_")} for r in approval_requests]
    if reqs:
        client.table("approval_requests").upsert(reqs, on_conflict="id").execute()
    if notifications:
        client.table("notifications").upsert(notifications, on_conflict="id").execute()


def apply_decision_to_supabase(client, result: dict) -> None:
    upd = result["approval_request_update"]
    client.table("approval_requests").update({
        "status": upd["status"],
        "approver_id": upd["approver_id"],
        "decided_at": upd["decided_at"],
    }).eq("id", upd["id"]).execute()
    tx = result["transaction_update"]
    client.table("transactions").update({"status": tx["status"]}).eq(
        "id", tx["transaction_id"]
    ).execute()
    client.table("notifications").upsert(
        [result["notification"]], on_conflict="id"
    ).execute()


def persist_reports_output(client, assignments: list[dict], reports: list[dict]) -> dict:
    # Persist all transaction -> event_group_id assignments in a SINGLE round-trip via
    # the apply_event_groups() RPC. The old code did one UPDATE per transaction, which
    # meant thousands of sequential HTTP calls and a 60s gateway timeout on batch runs.
    by_group: dict[str, list[str]] = {}
    for item in assignments:
        by_group.setdefault(item["event_group_id"], []).append(str(item["transaction_id"]))

    updated_groups = 0
    if assignments:
        try:
            client.rpc("apply_event_groups", {"assignments": assignments}).execute()
            updated_groups = len(assignments)
        except Exception:  # noqa: BLE001 — RPC not installed yet: fall back to grouped updates
            for group_id, tids in by_group.items():
                client.table("transactions").update(
                    {"event_group_id": group_id}
                ).in_("id", tids).execute()
            updated_groups = len(assignments)

    inserted_reports = 0
    clean_reports = [{k: v for k, v in r.items() if not k.startswith("_")} for r in reports]
    if clean_reports:
        client.table("expense_reports").upsert(clean_reports, on_conflict="id").execute()
        inserted_reports = len(clean_reports)

    return {
        "event_groups_updated": updated_groups,
        "event_group_count": len(by_group),
        "reports_upserted": inserted_reports,
    }


def employee_name_map(client) -> dict[str, str]:
    emp_df = fetch_table(client, "employees")
    names: dict[str, str] = {}
    if emp_df.empty:
        return names
    for _, r in emp_df.iterrows():
        parts = [
            str(r.get(c, "")).strip()
            for c in ("first_name", "last_name")
            if c in emp_df.columns
        ]
        names[str(r["id"])] = " ".join(p for p in parts if p).strip()
    return names


def flag_counts_for_transactions(client, transaction_ids: list[str]) -> dict[str, int]:
    if not transaction_ids:
        return {}
    counts: dict[str, int] = defaultdict(int)
    res = (
        client.table("transaction_flags")
        .select("transaction_id")
        .in_("transaction_id", transaction_ids)
        .execute()
    )
    for row in res.data or []:
        counts[str(row["transaction_id"])] += 1
    return dict(counts)


def list_transactions_page(client, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    res = (
        client.table("transactions")
        .select("*")
        .order("date", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data or []
    emp_names = employee_name_map(client)
    tx_ids = [str(r["id"]) for r in rows]
    flag_counts = flag_counts_for_transactions(client, tx_ids)

    items: list[dict[str, Any]] = []
    for r in rows:
        tid = str(r["id"])
        emp_id = str(r.get("employee_id", ""))
        status = str(r.get("status", "pending"))
        if flag_counts.get(tid, 0) > 0 and status == "pending":
            status = "flagged"
        items.append({
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

    return {
        "items": items,
        "has_more": len(items) == limit,
        "limit": limit,
        "offset": offset,
    }


def list_flags_enriched(client) -> list[dict]:
    flags_df = fetch_table(client, "transaction_flags")
    if flags_df.empty:
        return []

    tx_df = fetch_table(client, "transactions")
    emp_df = fetch_table(client, "employees")
    dept_df = fetch_table(client, "departments")

    emp_names: dict[str, str] = {}
    if not emp_df.empty:
        for _, r in emp_df.iterrows():
            parts = [str(r.get(c, "")).strip() for c in ("first_name", "last_name") if c in emp_df.columns]
            emp_names[str(r["id"])] = " ".join(p for p in parts if p).strip()

    tx_by_id: dict[str, dict] = {}
    for _, r in tx_df.iterrows():
        tid = str(r["id"])
        emp_id = str(r.get("employee_id", ""))
        tx_by_id[tid] = {
            "id": tid,
            "employee_id": emp_id,
            "employee_name": emp_names.get(emp_id, emp_id),
            "date": str(r.get("date", ""))[:10],
            "amount": float(r.get("amount", 0)),
            "merchant_name": str(r.get("merchant_name", "")),
            "merchant_category": str(r.get("merchant_category", "")),
            "city": str(r.get("city", "")),
            "status": str(r.get("status", "pending")),
            "flag_count": 0,
        }

    flag_counts: dict[str, int] = defaultdict(int)
    for _, r in flags_df.iterrows():
        flag_counts[str(r["transaction_id"])] += 1

    out: list[dict] = []
    for _, r in flags_df.iterrows():
        tid = str(r["transaction_id"])
        tx = tx_by_id.get(tid)
        reviewed = bool(r.get("reviewed", False))
        out.append({
            "id": str(r["id"]),
            "transaction_id": tid,
            "warning_message": str(r.get("warning_message", "")),
            "weight": int(r.get("weight", 1)),
            "reviewed": reviewed,
            "employee_name": tx["employee_name"] if tx else None,
            "transaction": {**tx, "flag_count": flag_counts[tid]} if tx else None,
        })
    out.sort(key=lambda x: (-x["weight"], x["reviewed"]))
    return out


def list_approvals_enriched(client) -> list[dict]:
    from feature3 import budget_status, department_spend, spend_history

    reqs_df = fetch_table(client, "approval_requests")
    if reqs_df.empty:
        return []

    df, flags, strikes, budgets = load_all_from_supabase(client)
    dept_spend = department_spend(df)

    out: list[dict] = []
    for _, req in reqs_df.iterrows():
        tid = str(req.get("transaction_id", ""))
        match = df[df["id"] == tid]
        if match.empty:
            continue
        row = match.iloc[0]
        ctx_spend = spend_history(df, row)
        budget = budget_status(row, budgets, dept_spend)
        tx_flags = flags.get(tid, [])

        recent = ctx_spend.get("recent") or []
        recent_expenses = [
            {"date": x["date"], "merchant": x["merchant"], "amount": x["amount"]}
            for x in recent[:5]
        ]

        out.append({
            "id": str(req["id"]),
            "transaction_id": tid,
            "employee_id": str(req.get("employee_id", row["employee_id"])),
            "employee_name": (
                str(row["employee_name"]) if pd.notna(row.get("employee_name")) else str(row["employee_id"])
            ),
            "department_name": (
                str(row["department"]) if pd.notna(row.get("department")) else "Unknown"
            ),
            "amount": float(req.get("amount", row["amount"])),
            "reason": str(req.get("reason", "")),
            "ai_recommendation": str(req.get("ai_recommendation") or "review"),
            "ai_reasoning": str(req.get("ai_reasoning") or ""),
            "status": str(req.get("status", "pending")),
            "department_budget_remaining": budget["remaining"] if budget else 0,
            "recent_expenses": recent_expenses,
            "_flag_count": len(tx_flags),
        })
    return out


def list_expense_reports(client) -> list[dict]:
    df = fetch_table(client, "expense_reports")
    if df.empty:
        return []
    return df.to_dict(orient="records")


def list_policies(client) -> list[dict]:
    df = fetch_table(client, "policies")
    if df.empty:
        return []
    records = df.to_dict(orient="records")
    records.sort(key=lambda r: str(r.get("effective_date", "")), reverse=True)
    return records


def upsert_policy(client, row: dict) -> dict:
    res = client.table("policies").upsert(row, on_conflict="id").execute()
    if not res.data:
        raise RuntimeError("Failed to upsert policy")
    return res.data[0]


def insert_policies(client, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    res = client.table("policies").upsert(rows, on_conflict="id").execute()
    return res.data or rows


def deactivate_policy(client, policy_id: str) -> dict:
    res = (
        client.table("policies")
        .update({"active": False})
        .eq("id", policy_id)
        .execute()
    )
    if not res.data:
        raise KeyError(f"Policy {policy_id} not found")
    return res.data[0]


def delete_policy(client, policy_id: str) -> None:
    """Permanently remove a policy row (use PATCH active=false to disable only)."""
    res = client.table("policies").delete().eq("id", policy_id).execute()
    if not res.data:
        raise KeyError(f"Policy {policy_id} not found")


def list_notifications(client, unread_only: bool = False) -> list[dict]:
    query = client.table("notifications").select("*")
    if unread_only:
        query = query.eq("read", False)
    res = query.order("created_at", desc=True).execute()
    return res.data or []


def mark_notification_read(client, notification_id: str) -> dict:
    res = (
        client.table("notifications")
        .update({"read": True})
        .eq("id", notification_id)
        .execute()
    )
    if not res.data:
        raise KeyError(f"Notification {notification_id} not found")
    return res.data[0]
