"""
Feature 3 — Approval Notifications & Decision Engine
====================================================
Self-contained pipeline that turns `transactions` (the ones that need a human
sign-off) into approval-ready notifications for the company approver.

When a transaction needs approval, this engine gives the approver everything in
one shot — the request, the employee's spend history, the department's budget
status, and an AI approve/deny recommendation with reasoning — so the approver
decides once. No back-and-forth.

  e.g. "Sarah from Marketing is requesting $1,200 for a conference registration.
        Her department has $3,400 remaining in Q2 budget. She attended 2 similar
        expenses this year. Recommendation: Approve — within policy, aligns with
        past pattern."

Speaks the team's Supabase schema directly:

  INPUTS (CSV files mirroring the tables; only `transactions` is required):
    transactions      id, employee_id, date, amount, merchant_name, merchant_category,
                      city, latitude, longitude, event_group_id, status   (amount is CAD)
    transaction_flags transaction_id, warning_message, weight             (optional, Feature 2)
    budgets           department_id, budget, quarter (Q1..Q4), year        (optional)
    employees         id, first_name, last_name, department_id            (optional)
    departments       id, department_name                                 (optional)
    employee_strikes  employee_id, strike_description, strike_date, amount_cheated (optional)

  OUTPUT (JSON — ready to write back to Supabase):
    {
      "approval_requests": [ {id, transaction_id, employee_id, amount, reason,
                              ai_recommendation, ai_reasoning, status,
                              approver_id, decided_at} ]               -> INSERT approval_requests
      "notifications":     [ {id, type, reference_id, message, read,
                              created_at} ]                            -> INSERT notifications
      "approver_emails":   [ {approval_request_id, to, subject, text,
                              html, deep_link} ]                       -> send via Supabase/Resend
    }

What it does:
  1. Map each transaction to its employee, department and budget context.
  2. Select transactions that need approval: amount over the threshold OR a
     compliance flag whose weight is high enough.
  3. Build the approver context: employee spend history + department budget status.
  4. Produce an AI approve/review/deny recommendation that reasons over the
     numbers (LLM, with a deterministic fallback and a --mock-llm path).
  5. Emit approval_requests + notifications (sidebar badge + flag list) +
     approver email payloads (with a deep link to the flag/approval).

Decision mode (--decide): the approver replies once and the decision is processed —
updates the approval_request, the transaction status, and emails the employee.

Supabase (temporaire — section commentée en bas du fichier) :
  Env vars : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
  Activer  : décommenter la section Supabase + le flag --supabase + pip install supabase
  Défaut   : CSV inchangé (comportement actuel)

Usage:
    py feature3.py --transactions transactions.csv --out feature3_output.json
    py feature3.py --transactions transactions.csv --flags transaction_flags.csv \
        --budgets budgets.csv --employees employees.csv --departments departments.csv \
        --strikes employee_strikes.csv --threshold 1000 --out feature3_output.json
    py feature3.py --transactions transactions.csv --mock-llm        # no API calls
    py feature3.py --transactions transactions.csv --decide <transaction_id> \
        --decision approve --approver-id cfo-1                        # process a decision
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import pandas as pd

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# =========================================================================== #
# Config
# =========================================================================== #

DEFAULT_MODEL = "gemini-2.5-flash"
APPROVAL_THRESHOLD_CAD = 1000.0   # amount over this needs approval (override via --threshold)
FLAG_NOTIFY_WEIGHT = 3            # a flag at/above this weight triggers an approver email
DENY_WEIGHT = 4                   # a flag at/above this weight is a clear violation
RECO_BATCH_SIZE = 25              # approval requests per recommendation LLM call
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://app.brim.example")

# Stable namespace so approval_request / notification ids are reproducible across
# runs (lets --decide find a request again without a persisted id).
_NS = uuid.UUID("3f3e7b6a-0000-4000-8000-000000000003")


def get_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def make_chat_llm(temperature: float = 0):
    """Chat LLM with Gemini 'thinking' disabled by default (faster for extraction)."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = {"model": get_model(), "temperature": temperature}
    if os.getenv("GEMINI_THINKING", "0") == "0":
        kwargs["thinking_budget"] = 0
    return ChatGoogleGenerativeAI(**kwargs)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _approval_id(transaction_id: str) -> str:
    return str(uuid.uuid5(_NS, f"approval:{transaction_id}"))


def _notification_id(kind: str, reference_id: str) -> str:
    return str(uuid.uuid5(_NS, f"notification:{kind}:{reference_id}"))


def _cad(amount: float) -> str:
    return f"${amount:,.2f} CAD"


# =========================================================================== #
# Dates / quarters
# =========================================================================== #

def _parse_date(s: Any):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _quarter_of(d: datetime | None) -> str | None:
    if d is None:
        return None
    return f"Q{(d.month - 1) // 3 + 1}"


def _year_of(d: datetime | None) -> int | None:
    return d.year if d is not None else None


def _normalize_quarter(value: Any) -> str | None:
    if pd.isna(value):
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s.startswith("Q"):
        s = s[1:]
    try:
        q = int(float(s))
    except ValueError:
        return None
    return f"Q{q}" if 1 <= q <= 4 else None


# =========================================================================== #
# Loaders (Supabase-shaped CSVs)
# =========================================================================== #

def _normalize_transactions_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw transactions DataFrame (CSV or Supabase)."""
    df = df.copy()
    df["id"] = df["id"].astype(str)
    df["employee_id"] = df["employee_id"].astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0).round(2)
    for col in ("merchant_name", "merchant_category", "city", "status"):
        if col not in df.columns:
            df[col] = None
    df["_d"] = df["date"].map(_parse_date)
    df["_year"] = df["_d"].map(_year_of)
    df["_quarter"] = df["_d"].map(_quarter_of)
    return df


def _prepare_employees_for_merge(emp: pd.DataFrame | None,
                               dept: pd.DataFrame | None) -> pd.DataFrame | None:
    if emp is None or emp.empty:
        return None
    emp = emp.copy()
    emp["id"] = emp["id"].astype(str)
    parts = [c for c in ("first_name", "last_name") if c in emp.columns]
    if parts:
        emp["employee_name"] = emp[parts].fillna("").agg(" ".join, axis=1).str.strip()
    if "department_id" in emp.columns:
        emp["department_id"] = emp["department_id"].astype(str)
        if dept is not None and not dept.empty and {"id", "department_name"}.issubset(dept.columns):
            dept = dept.copy()
            dept["id"] = dept["id"].astype(str)
            emp = emp.merge(
                dept.rename(columns={"id": "department_id", "department_name": "department"}),
                on="department_id", how="left")
    keep = ["id"] + [c for c in ("employee_name", "department", "department_id") if c in emp.columns]
    return emp[keep].rename(columns={"id": "employee_id"})


def _enrich_transactions(df: pd.DataFrame, emp: pd.DataFrame | None,
                         dept: pd.DataFrame | None) -> pd.DataFrame:
    """Attach employee name + department to transactions (shared by CSV and Supabase loaders)."""
    df = _normalize_transactions_columns(df)
    df["employee_name"] = None
    df["department"] = None
    df["department_id"] = None
    emp_merge = _prepare_employees_for_merge(emp, dept)
    if emp_merge is not None:
        df = df.drop(columns=["employee_name", "department", "department_id"], errors="ignore").merge(
            emp_merge, on="employee_id", how="left")
    return df


def load_transactions(path: str, employees_path: str | None,
                      departments_path: str | None) -> pd.DataFrame:
    """Read the transactions table and attach employee name + department (id & name)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    emp = pd.read_csv(employees_path, encoding="utf-8-sig") if employees_path else None
    dept = pd.read_csv(departments_path, encoding="utf-8-sig") if departments_path else None
    return _enrich_transactions(df, emp, dept)


def _flags_from_df(df: pd.DataFrame) -> dict[str, list[dict]]:
    flags: dict[str, list[dict]] = defaultdict(list)
    for _, r in df.iterrows():
        tid = str(r["transaction_id"])
        flags[tid].append({
            "warning_message": str(r.get("warning_message", "")),
            "weight": float(pd.to_numeric(r.get("weight"), errors="coerce") or 0.0),
        })
    return flags


def load_flags(path: str | None) -> dict[str, list[dict]]:
    """transaction_flags -> {transaction_id: [ {warning_message, weight}, ... ]}."""
    if not path:
        return defaultdict(list)
    return _flags_from_df(pd.read_csv(path, encoding="utf-8-sig"))


def _strikes_from_df(df: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for emp, g in df.groupby("employee_id"):
        out[str(emp)] = {
            "count": int(len(g)),
            "total_cheated": round(float(pd.to_numeric(g.get("amount_cheated"), errors="coerce").fillna(0).sum()), 2),
            "descriptions": [str(x) for x in g.get("strike_description", pd.Series([])).tolist()][:5],
        }
    return out


def load_strikes(path: str | None) -> dict[str, dict]:
    """employee_strikes -> {employee_id: {count, total_cheated, descriptions[]}}."""
    if not path:
        return {}
    return _strikes_from_df(pd.read_csv(path, encoding="utf-8-sig"))


def _budgets_from_df(df: pd.DataFrame) -> dict[tuple[str, str, int], float]:
    out: dict[tuple[str, str, int], float] = {}
    dept_col = "department_id" if "department_id" in df.columns else (
        "department" if "department" in df.columns else df.columns[0])
    for _, r in df.iterrows():
        dept = str(r.get(dept_col))
        quarter = _normalize_quarter(r.get("quarter"))
        year = pd.to_numeric(r.get("year"), errors="coerce")
        budget = pd.to_numeric(r.get("budget"), errors="coerce")
        if dept and quarter and not pd.isna(year) and not pd.isna(budget):
            out[(dept, quarter, int(year))] = round(float(budget), 2)
    return out


def load_budgets(path: str | None) -> dict[tuple[str, str, int], float]:
    """budgets -> {(department_id, quarter, year): budget_total}."""
    if not path:
        return {}
    return _budgets_from_df(pd.read_csv(path, encoding="utf-8-sig"))


# =========================================================================== #
# Supabase (temporaire — décommenter quand prêt)
# =========================================================================== #
# Requires: pip install supabase  (see requirements.txt)
# Env vars: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
# TODO: confirm table/column names match your Supabase schema (especially `budgets`).
#
# def get_supabase_client():
#     from supabase import create_client
#     url = os.getenv("SUPABASE_URL")
#     key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
#     if not url or not key:
#         raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
#     return create_client(url, key)
#
#
# def _fetch_table(client, table: str, select: str = "*") -> pd.DataFrame:
#     """Fetch a Supabase table into a DataFrame (empty if no rows)."""
#     res = client.table(table).select(select).execute()
#     rows = res.data or []
#     return pd.DataFrame(rows) if rows else pd.DataFrame()
#
#
# def load_all_from_supabase(client):
#     """Load all inputs from Supabase; returns (df, flags, strikes, budgets) like the CSV path."""
#     tx_df = _fetch_table(client, "transactions")
#     if tx_df.empty:
#         raise RuntimeError("No rows in Supabase table `transactions`")
#     flags_df = _fetch_table(client, "transaction_flags")
#     strikes_df = _fetch_table(client, "employee_strikes")
#     emp_df = _fetch_table(client, "employees")
#     dept_df = _fetch_table(client, "departments")
#     budgets_df = _fetch_table(client, "budgets")  # TODO: rename if table is `Budget`
#     df = _enrich_transactions(tx_df, emp_df if not emp_df.empty else None,
#                               dept_df if not dept_df.empty else None)
#     flags = _flags_from_df(flags_df) if not flags_df.empty else {}
#     strikes = _strikes_from_df(strikes_df) if not strikes_df.empty else {}
#     budgets = _budgets_from_df(budgets_df) if not budgets_df.empty else {}
#     return df, flags, strikes, budgets
#
#
# def persist_pipeline_to_supabase(client, approval_requests: list[dict],
#                                  notifications: list[dict]) -> None:
#     """INSERT pipeline output into Supabase (strips internal _ctx fields)."""
#     reqs = [{k: v for k, v in r.items() if not k.startswith("_")} for r in approval_requests]
#     if reqs:
#         client.table("approval_requests").upsert(reqs, on_conflict="id").execute()
#     if notifications:
#         client.table("notifications").upsert(notifications, on_conflict="id").execute()
#     print(f"[supabase: upserted {len(reqs)} approval_requests, {len(notifications)} notifications]",
#           file=sys.stderr)
#
#
# def apply_decision_to_supabase(client, result: dict) -> None:
#     """Apply --decide output to Supabase (approval_request + transaction + notification)."""
#     upd = result["approval_request_update"]
#     client.table("approval_requests").update({
#         "status": upd["status"],
#         "approver_id": upd["approver_id"],
#         "decided_at": upd["decided_at"],
#     }).eq("id", upd["id"]).execute()
#     tx = result["transaction_update"]
#     client.table("transactions").update({"status": tx["status"]}).eq("id", tx["transaction_id"]).execute()
#     client.table("notifications").insert(result["notification"]).execute()
#     print(f"[supabase: decision applied on {upd['id']}]", file=sys.stderr)


# =========================================================================== #
# Context: employee spend history + department budget status
# =========================================================================== #

def department_spend(df: pd.DataFrame) -> dict[tuple[str, str, int], float]:
    """Total committed spend per (department_id, quarter, year)."""
    spend: dict[tuple[str, str, int], float] = defaultdict(float)
    for _, r in df.iterrows():
        dept = r.get("department_id")
        if dept is None or pd.isna(dept) or r["_quarter"] is None or r["_year"] is None:
            continue
        spend[(str(dept), r["_quarter"], int(r["_year"]))] += float(r["amount"])
    return spend


def budget_status(row: pd.Series, budgets: dict, dept_spend: dict) -> dict | None:
    """Department budget remaining for the request's quarter, excluding this request."""
    dept = row.get("department_id")
    quarter, year = row["_quarter"], row["_year"]
    if dept is None or pd.isna(dept) or quarter is None or year is None:
        return None
    key = (str(dept), quarter, int(year))
    if key not in budgets:
        return None
    budget_total = budgets[key]
    committed = dept_spend.get(key, 0.0)
    # "remaining" = budget minus everything else already committed (not this request).
    remaining = round(budget_total - (committed - float(row["amount"])), 2)
    return {
        "quarter": quarter,
        "year": int(year),
        "budget_total": round(budget_total, 2),
        "department_spent": round(committed - float(row["amount"]), 2),
        "remaining": remaining,
    }


def spend_history(df: pd.DataFrame, row: pd.Series) -> dict:
    """Employee's spend pattern: YTD totals + prior similar expenses + recent activity."""
    emp_id = str(row["employee_id"])
    year = row["_year"]
    emp_tx = df[df["employee_id"] == emp_id]
    ytd = emp_tx[emp_tx["_year"] == year] if year is not None else emp_tx
    cat = str(row.get("merchant_category"))
    similar = ytd[(ytd["merchant_category"].astype(str) == cat) & (ytd["id"] != row["id"])]
    recent = emp_tx.sort_values("_d", ascending=False, na_position="last").head(5)
    return {
        "ytd_count": int(len(ytd)),
        "ytd_total": round(float(ytd["amount"].sum()), 2),
        "similar_prior_count": int(len(similar)),
        "recent": [
            {"date": str(r["date"])[:10], "merchant": str(r["merchant_name"]),
             "amount": round(float(r["amount"]), 2)}
            for _, r in recent.iterrows()
        ],
    }


# =========================================================================== #
# Selection: which transactions need approval
# =========================================================================== #

def needs_approval(row: pd.Series, tx_flags: list[dict], threshold: float) -> bool:
    if float(row["amount"]) > threshold:
        return True
    return any(f["weight"] >= FLAG_NOTIFY_WEIGHT for f in tx_flags)


def _reason_for(row: pd.Series, tx_flags: list[dict], threshold: float) -> str:
    msgs = [f["warning_message"] for f in tx_flags if f.get("warning_message")]
    if msgs:
        return " | ".join(msgs[:3])
    return f"Montant {_cad(float(row['amount']))} dépasse le seuil d'approbation de {_cad(threshold)}."


# =========================================================================== #
# AI approval recommendation (reasons over budget + spend history + flags)
# =========================================================================== #

RECO_SYSTEM = """You are an AI expense-approval assistant for a corporate finance team.
For each request you receive the employee, department, amount (CAD), the reason it needs
approval, the department's budget status for the quarter, the employee's spend history,
any compliance warnings (each with a severity weight 1-5), and the employee's strike history.
Recommend exactly one of: "approve", "review", or "deny" for the approver.
- approve: within policy and budget, consistent with the employee's past pattern.
- review: needs a human look (over/near budget, large amount, low-weight warnings, thin context).
- deny: clear violation (high-weight warning, or a repeat offender with prior strikes,
        or clearly over the remaining budget without justification).
Reference the actual numbers: amount vs remaining budget, prior similar expenses, warnings,
strikes. Be concise (1-2 sentences), like:
"Sarah is requesting $1,200; Marketing has $3,400 left in Q2 and she has 2 similar expenses
this year. Approve - within policy, aligns with past pattern." """

RECO_HUMAN = """Requests (JSON array). Return one recommendation per request, echoing request_id.

{requests_json}

Recommend for all {n}."""


def _reco_schema():
    from pydantic import BaseModel, Field

    class Reco(BaseModel):
        request_id: str
        recommendation: str = Field(description='"approve" | "review" | "deny"')
        reasoning: str = Field(description="1-2 sentences referencing amount/budget/history/warnings")

    class Batch(BaseModel):
        recommendations: list[Reco]

    return Batch


def _deterministic_reco(ctx: dict, threshold: float) -> tuple[str, str]:
    flags = ctx["warnings"]
    strikes = ctx["strike_history"]
    budget = ctx["budget"]
    amount = ctx["amount_cad"]
    max_w = max((f["weight"] for f in flags), default=0.0)
    n_strikes = strikes["count"] if strikes else 0
    over_budget = bool(budget) and amount > budget["remaining"]

    budget_txt = (f"{ctx['department']} a {_cad(budget['remaining'])} restant en "
                  f"{budget['quarter']} {budget['year']}" if budget else "budget non disponible")
    base = (f"{ctx['employee']} demande {_cad(amount)}; {budget_txt}; "
            f"{ctx['spend_history']['similar_prior_count']} dépense(s) similaire(s) cette année")

    if max_w >= DENY_WEIGHT or n_strikes >= 2:
        return "deny", (f"{base}. Refus — avertissement de conformité élevé "
                        f"(poids max {max_w:g}) ou {n_strikes} antécédent(s).")
    if over_budget:
        return "review", (f"{base}. À revoir — la demande dépasse le budget restant.")
    if flags:
        return "review", (f"{base}. À revoir — {len(flags)} avertissement(s) de conformité "
                          f"(poids max {max_w:g}).")
    if amount > threshold:
        return "review", (f"{base}. À revoir — montant au-dessus du seuil "
                          f"de {_cad(threshold)}, aucun avertissement.")
    return "approve", (f"{base}. Approbation — dans la politique et le budget, "
                       f"cohérent avec l'historique.")


def recommend(requests: list[dict], threshold: float, use_llm: bool) -> None:
    """Fill ai_recommendation / ai_reasoning on each request (in place)."""
    if not requests:
        return
    if use_llm:
        try:
            from langchain_core.prompts import ChatPromptTemplate
            chain = ChatPromptTemplate.from_messages(
                [("system", RECO_SYSTEM), ("human", RECO_HUMAN)]
            ) | make_chat_llm().with_structured_output(_reco_schema())
            by_id: dict[str, Any] = {}
            for start in range(0, len(requests), RECO_BATCH_SIZE):
                batch = requests[start:start + RECO_BATCH_SIZE]
                slim = [{
                    "request_id": r["id"],
                    "employee": r["_ctx"]["employee"],
                    "department": r["_ctx"]["department"],
                    "amount_cad": r["_ctx"]["amount_cad"],
                    "reason": r["reason"],
                    "budget": r["_ctx"]["budget"],
                    "spend_history": r["_ctx"]["spend_history"],
                    "warnings": r["_ctx"]["warnings"],
                    "strike_history": r["_ctx"]["strike_history"],
                } for r in batch]
                res = chain.invoke({"requests_json": json.dumps(slim, ensure_ascii=False),
                                    "n": len(batch)})
                by_id.update({x.request_id: x for x in res.recommendations})
            for r in requests:
                x = by_id.get(r["id"])
                if x and x.recommendation in ("approve", "review", "deny"):
                    r["ai_recommendation"] = x.recommendation
                    r["ai_reasoning"] = x.reasoning
                else:
                    r["ai_recommendation"], r["ai_reasoning"] = _deterministic_reco(r["_ctx"], threshold)
            print(f"[reco: {len(requests)} judged by {get_model()}]", file=sys.stderr)
            return
        except Exception as exc:  # noqa: BLE001 — degrade to deterministic, never hard-fail
            print(f"[reco LLM unavailable: {exc}] -> deterministic", file=sys.stderr)

    for r in requests:
        r["ai_recommendation"], r["ai_reasoning"] = _deterministic_reco(r["_ctx"], threshold)
    print(f"[reco: {len(requests)} judged deterministically]", file=sys.stderr)


# =========================================================================== #
# Email payloads (generated here; sent via Supabase / Resend downstream)
# =========================================================================== #

def approver_email(req: dict, approver_to: str) -> dict:
    ctx = req["_ctx"]
    deep_link = f"{APP_BASE_URL}/approvals/{req['id']}"
    reco = req["ai_recommendation"].upper()
    budget = ctx["budget"]
    budget_line = (f"Budget {budget['quarter']} {budget['year']} : "
                   f"{_cad(budget['remaining'])} restant." if budget else
                   "Budget départemental : non disponible.")
    subject = f"[Approbation requise] {ctx['employee']} — {_cad(ctx['amount_cad'])} ({reco})"
    text = (
        f"{ctx['employee']} ({ctx['department'] or 'département inconnu'}) demande "
        f"{_cad(ctx['amount_cad'])}.\n"
        f"Motif : {req['reason']}\n"
        f"{budget_line}\n"
        f"Recommandation IA : {reco} — {req['ai_reasoning']}\n\n"
        f"Décider : {deep_link}\n"
    )
    html = (
        f"<div style=\"font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:560px\">"
        f"<h2 style=\"margin:0 0 8px\">Approbation requise</h2>"
        f"<p style=\"margin:0 0 4px\"><strong>{ctx['employee']}</strong> "
        f"({ctx['department'] or 'département inconnu'}) demande "
        f"<strong>{_cad(ctx['amount_cad'])}</strong>.</p>"
        f"<p style=\"margin:0 0 4px;color:#555\">Motif : {req['reason']}</p>"
        f"<p style=\"margin:0 0 4px;color:#555\">{budget_line}</p>"
        f"<p style=\"margin:8px 0\"><strong>Recommandation IA : {reco}</strong><br>"
        f"<span style=\"color:#555\">{req['ai_reasoning']}</span></p>"
        f"<p><a href=\"{deep_link}\" "
        f"style=\"display:inline-block;padding:10px 16px;background:#111;color:#fff;"
        f"border-radius:8px;text-decoration:none\">Voir &amp; décider</a></p>"
        f"</div>"
    )
    return {
        "approval_request_id": req["id"],
        "to": approver_to,
        "subject": subject,
        "text": text,
        "html": html,
        "deep_link": deep_link,
    }


def employee_decision_email(req: dict, decision: str, employee_to: str) -> dict:
    ctx = req["_ctx"]
    deep_link = f"{APP_BASE_URL}/approvals/{req['id']}"
    approved = decision == "approve"
    verdict = "approuvée" if approved else "refusée"
    subject = f"Votre demande de {_cad(ctx['amount_cad'])} a été {verdict}"
    text = (
        f"Bonjour {ctx['employee']},\n\n"
        f"Votre demande de {_cad(ctx['amount_cad'])} ({req['reason']}) a été {verdict}.\n"
        f"Détails : {deep_link}\n"
    )
    html = (
        f"<div style=\"font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:560px\">"
        f"<p>Bonjour {ctx['employee']},</p>"
        f"<p>Votre demande de <strong>{_cad(ctx['amount_cad'])}</strong> "
        f"({req['reason']}) a été <strong>{verdict}</strong>.</p>"
        f"<p><a href=\"{deep_link}\">Voir les détails</a></p>"
        f"</div>"
    )
    return {
        "approval_request_id": req["id"],
        "to": employee_to,
        "subject": subject,
        "text": text,
        "html": html,
        "deep_link": deep_link,
    }


def send_email_resend(payload: dict, from_addr: str) -> bool:
    """Optional direct send via Resend (guarded import; no-op without a key)."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key or not payload.get("to"):
        return False
    try:
        import resend

        resend.api_key = api_key
        resend.Emails.send({
            "from": from_addr,
            "to": payload["to"],
            "subject": payload["subject"],
            "html": payload["html"],
            "text": payload["text"],
        })
        return True
    except Exception as exc:  # noqa: BLE001 — sending must never crash the pipeline
        print(f"[resend send failed: {exc}]", file=sys.stderr)
        return False


# =========================================================================== #
# Build approval_requests + notifications + approver emails
# =========================================================================== #

def build_pipeline(df: pd.DataFrame, flags: dict, strikes: dict, budgets: dict,
                   threshold: float, approver_to: str, use_llm: bool,
                   ) -> tuple[list[dict], list[dict], list[dict]]:
    dept_spend = department_spend(df)

    notifications: list[dict] = []
    seen_flag_tx: set[str] = set()
    approval_requests: list[dict] = []

    for _, row in df.iterrows():
        tid = str(row["id"])
        tx_flags = flags.get(tid, [])

        # Flag notification (sidebar badge + flag list) for every flagged transaction.
        if tx_flags and tid not in seen_flag_tx:
            seen_flag_tx.add(tid)
            max_w = max(f["weight"] for f in tx_flags)
            msg = tx_flags[0]["warning_message"] or "Transaction signalée par le moteur de conformité."
            notifications.append({
                "id": _notification_id("flag", tid),
                "type": "flag",
                "reference_id": tid,
                "message": f"Transaction signalée ({_cad(float(row['amount']))}) : {msg}",
                "read": False,
                "created_at": _now_iso(),
                "_weight": max_w,
            })

        if not needs_approval(row, tx_flags, threshold):
            continue

        req_id = _approval_id(tid)
        emp_id = str(row["employee_id"])
        ctx = {
            "employee": (row.get("employee_name") if pd.notna(row.get("employee_name")) else None) or emp_id,
            "department": row.get("department") if pd.notna(row.get("department")) else None,
            "amount_cad": round(float(row["amount"]), 2),
            "budget": budget_status(row, budgets, dept_spend),
            "spend_history": spend_history(df, row),
            "warnings": tx_flags,
            "strike_history": strikes.get(emp_id),
        }
        approval_requests.append({
            "id": req_id,
            "transaction_id": tid,
            "employee_id": emp_id,
            "amount": round(float(row["amount"]), 2),
            "reason": _reason_for(row, tx_flags, threshold),
            "ai_recommendation": None,   # filled by recommend()
            "ai_reasoning": None,
            "status": "pending",
            "approver_id": None,
            "decided_at": None,
            "_ctx": ctx,
        })

    recommend(approval_requests, threshold, use_llm)

    # Approval notification + approver email per request.
    emails: list[dict] = []
    for req in approval_requests:
        notifications.append({
            "id": _notification_id("approval", req["id"]),
            "type": "approval",
            "reference_id": req["id"],
            "message": (f"Approbation requise : {req['_ctx']['employee']} — "
                        f"{_cad(req['amount'])} (reco : {req['ai_recommendation']})"),
            "read": False,
            "created_at": _now_iso(),
        })
        emails.append(approver_email(req, approver_to))

    notifications.sort(key=lambda n: n.get("_weight", 0.0), reverse=True)
    for n in notifications:
        n.pop("_weight", None)
    return approval_requests, notifications, emails


# =========================================================================== #
# Decision processing (--decide): approver replies once, decision is processed
# =========================================================================== #

def process_decision(df: pd.DataFrame, flags: dict, strikes: dict, budgets: dict,
                     threshold: float, transaction_id: str, decision: str,
                     approver_id: str | None, employee_to: str) -> dict:
    """Process an approve/deny on one transaction. No back-and-forth."""
    decision = decision.lower().strip()
    if decision not in ("approve", "deny"):
        raise ValueError("decision must be 'approve' or 'deny'")

    match = df[df["id"] == str(transaction_id)]
    if match.empty:
        raise ValueError(f"transaction {transaction_id} not found")
    row = match.iloc[0]
    tid = str(row["id"])
    emp_id = str(row["employee_id"])
    tx_flags = flags.get(tid, [])

    ctx = {
        "employee": (row.get("employee_name") if pd.notna(row.get("employee_name")) else None) or emp_id,
        "department": row.get("department") if pd.notna(row.get("department")) else None,
        "amount_cad": round(float(row["amount"]), 2),
        "budget": budget_status(row, budgets, department_spend(df)),
        "spend_history": spend_history(df, row),
        "warnings": tx_flags,
        "strike_history": strikes.get(emp_id),
    }
    req = {
        "id": _approval_id(tid),
        "transaction_id": tid,
        "employee_id": emp_id,
        "amount": round(float(row["amount"]), 2),
        "reason": _reason_for(row, tx_flags, threshold),
        "ai_recommendation": None,
        "ai_reasoning": None,
        "status": "pending",
        "approver_id": None,
        "decided_at": None,
        "_ctx": ctx,
    }
    decided_at = _now_iso()
    tx_status = "approved" if decision == "approve" else "denied"
    req_status = "approved" if decision == "approve" else "denied"

    approval_update = {
        "id": req["id"],
        "transaction_id": tid,
        "employee_id": emp_id,
        "status": req_status,
        "approver_id": approver_id,
        "decided_at": decided_at,
    }
    transaction_update = {"transaction_id": tid, "status": tx_status}
    email = employee_decision_email(req, decision, employee_to)
    notification = {
        "id": _notification_id("decision", req["id"]),
        "type": "decision",
        "reference_id": req["id"],
        "message": f"Demande de {_cad(req['amount'])} {('approuvée' if decision == 'approve' else 'refusée')}.",
        "read": False,
        "created_at": decided_at,
    }
    return {
        "approval_request_update": approval_update,
        "transaction_update": transaction_update,
        "notification": notification,
        "employee_email": email,
    }


# =========================================================================== #
# Runner
# =========================================================================== #

def _strip_context(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Feature 3 — Approval Notifications & Decision Engine.")
    ap.add_argument("--transactions", required=True, help="transactions CSV (Supabase shape).")
    # TODO: make --transactions optional when --supabase is enabled (see commented block below).
    # ap.add_argument("--supabase", action="store_true",
    #                 help="Load from / write to Supabase instead of CSV (needs env vars).")
    ap.add_argument("--flags", default=None, help="transaction_flags CSV (optional).")
    ap.add_argument("--budgets", default=None, help="budgets CSV: department_id, budget, quarter, year (optional).")
    ap.add_argument("--employees", default=None)
    ap.add_argument("--departments", default=None)
    ap.add_argument("--strikes", default=None, help="employee_strikes CSV (optional).")
    ap.add_argument("--threshold", type=float, default=APPROVAL_THRESHOLD_CAD,
                    help=f"amount over this needs approval (default {APPROVAL_THRESHOLD_CAD:g} CAD).")
    ap.add_argument("--approver-to", default=os.getenv("APPROVER_EMAIL", "approver@company.com"))
    ap.add_argument("--from-addr", default=os.getenv("RESEND_FROM", "Brim <noreply@company.com>"))
    ap.add_argument("--model", default=None, help="Gemini model id (default gemini-2.5-flash).")
    ap.add_argument("--mock-llm", action="store_true", help="No API calls (deterministic recommendation).")
    ap.add_argument("--send", action="store_true", help="Also send emails directly via Resend (needs RESEND_API_KEY).")
    ap.add_argument("--decide", default=None, metavar="TRANSACTION_ID",
                    help="Decision mode: process a decision on this transaction id.")
    ap.add_argument("--decision", default=None, choices=["approve", "deny"], help="Decision for --decide.")
    ap.add_argument("--approver-id", default=None, help="Approver id recorded on the decision.")
    ap.add_argument("--employee-to", default=os.getenv("EMPLOYEE_EMAIL", "employee@company.com"))
    ap.add_argument("--out", default=None, help="Write JSON here (default stdout).")
    ap.add_argument("--keep-context", action="store_true", help="Keep internal _-prefixed context in output.")
    args = ap.parse_args()
    if args.model:
        os.environ["GEMINI_MODEL"] = args.model

    # ---- Supabase path (décommenter avec la section Supabase en haut du fichier) ----
    # if args.supabase:
    #     client = get_supabase_client()
    #     df, flags, strikes, budgets = load_all_from_supabase(client)
    # else:
    df = load_transactions(args.transactions, args.employees, args.departments)
    flags = load_flags(args.flags)
    strikes = load_strikes(args.strikes)
    budgets = load_budgets(args.budgets)
    use_llm = not args.mock_llm

    # ---- Decision mode -------------------------------------------------------
    if args.decide:
        if not args.decision:
            print("[--decide requires --decision approve|deny]", file=sys.stderr)
            return 2
        result = process_decision(df, flags, strikes, budgets, args.threshold,
                                   args.decide, args.decision, args.approver_id, args.employee_to)
        if args.send:
            result["employee_email"]["sent"] = send_email_resend(result["employee_email"], args.from_addr)
        # if args.supabase:
        #     apply_decision_to_supabase(client, result)
        output = {"feature": "3 - Approval Decision", **result}
        payload = json.dumps(output, indent=2, ensure_ascii=False)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(payload)
            print(f"[decision processed -> {args.out}]", file=sys.stderr)
        else:
            print(payload)
        return 0

    # ---- Pipeline mode -------------------------------------------------------
    try:
        approval_requests, notifications, emails = build_pipeline(
            df, flags, strikes, budgets, args.threshold, args.approver_to, use_llm)
        mode = get_model() if use_llm else "mock"
    except Exception as exc:  # noqa: BLE001 — never hard-fail; degrade to deterministic
        print(f"[pipeline LLM unavailable: {exc}] -> deterministic fallback", file=sys.stderr)
        approval_requests, notifications, emails = build_pipeline(
            df, flags, strikes, budgets, args.threshold, args.approver_to, use_llm=False)
        mode = "mock (fallback)"

    if args.send:
        for em in emails:
            em["sent"] = send_email_resend(em, args.from_addr)

    # if args.supabase:
    #     persist_pipeline_to_supabase(client, approval_requests, notifications)

    if not args.keep_context:
        approval_requests = _strip_context(approval_requests)

    output = {
        "feature": "3 - Approval Notifications & Decision Engine",
        "model": mode,
        "transaction_count": int(len(df)),
        "approval_request_count": len(approval_requests),
        "notification_count": len(notifications),
        "approval_requests": approval_requests,   # -> INSERT INTO approval_requests
        "notifications": notifications,           # -> INSERT INTO notifications
        "approver_emails": emails,                # -> send via Supabase / Resend
    }
    payload = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"[wrote {len(approval_requests)} approval requests + {len(notifications)} "
              f"notifications + {len(emails)} emails -> {args.out}]", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
