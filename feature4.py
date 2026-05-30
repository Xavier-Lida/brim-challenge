"""
Feature 4 — Automated Expense Report Generation
================================================
Self-contained pipeline that turns `transactions` into approval-ready `expense_reports`.

Speaks the team's Supabase schema directly:

  INPUTS (CSV files mirroring the tables; only `transactions` + `mcc_codes` required):
    transactions      id, employee_id, date, amount, merchant_name, merchant_category,
                      city, latitude, longitude, event_group_id, status   (amount is CAD)
    mcc_codes         mcc, edited_description, ...        (merchant_category == MCC code)
    transaction_flags transaction_id, warning_message, weight             (optional, Feature 2)
    employee_strikes  employee_id, strike_description, strike_date, amount_cheated (optional)
    employees         id, first_name, last_name, department_id            (optional)
    departments       id, department_name                                 (optional)

  OUTPUT (JSON — ready to write back to Supabase):
    {
      "transaction_event_groups": [ {transaction_id, event_group_id} ],   -> UPDATE transactions
      "expense_reports": [ {id, employee_id, event_group_id, title, date_from,
                            date_to, total_amount, status, pdf_url,
                            ai_recommendation, ai_reasoning} ]             -> INSERT expense_reports
    }

What it does:
  1. Map merchant_category (MCC) -> Brim spend category via mcc_codes.csv.
  2. Group each employee's transactions into events (deterministic spatiotemporal
     clustering: date proximity, with same-city/geo gaps held together so a trip
     survives a weekend; LLM only labels multi-item clusters). -> assigns event_group_id
  3. Pull policy flags (transaction_flags) + strike history (employee_strikes).
  4. Build one expense_report per event, with an LLM approve/deny recommendation that
     reasons over the flags + the employee's strike history.

Usage:
    py feature4.py --transactions transactions.csv --out feature4_output.json
    py feature4.py --transactions transactions.csv --flags transaction_flags.csv \
        --strikes employee_strikes.csv --employees employees.csv --departments departments.csv \
        --model gemini-3-flash-preview --out feature4_output.json
    py feature4.py --transactions transactions.csv --mock-llm        # no API calls
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime
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
DEFAULT_BRIM_CATEGORY = "Autre"
GROUP_GAP_DAYS = 4            # a date gap larger than this starts a new event (different place)
SAME_PLACE_GAP_BONUS = 3     # same-location clusters tolerate this many EXTRA gap days (weekends mid-trip)
GEO_SAME_KM = 50.0           # transactions within this distance count as the same place
LABEL_BATCH_SIZE = 40        # clusters per labeling LLM call
RECO_BATCH_SIZE = 40         # reports per recommendation LLM call
AUTO_APPROVE_MAX_CAD = 100.0 # trivial reports below this (1 item, no flags) auto-approve


def get_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def make_chat_llm(temperature: float = 0):
    """Chat LLM with Gemini 'thinking' disabled by default (faster for extraction)."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = {"model": get_model(), "temperature": temperature}
    if os.getenv("GEMINI_THINKING", "0") == "0":
        kwargs["thinking_budget"] = 0
    return ChatGoogleGenerativeAI(**kwargs)


# =========================================================================== #
# MCC -> Brim category mapping (driven by mcc_codes.csv)
# =========================================================================== #

MCC_OVERRIDES: dict[str, str] = {
    "5812": "Repas Client", "5813": "Repas Client", "5814": "Repas Personnel",
    "4121": "Transport Local", "4111": "Transport Local", "4131": "Transport Local",
    "4511": "Voyage", "5734": "Logiciel / IT", "7372": "Logiciel / IT",
    "5541": "Carburant", "5542": "Carburant",
    "5943": "Fournitures de bureau", "5111": "Fournitures de bureau",
    "4814": "Télécommunications",
}

KEYWORD_RULES: list[tuple[str, str]] = [
    (r"\bairline|air carrier|airways\b", "Voyage"),
    (r"\bhotel|motel|lodging|inn\b|resort|suites", "Voyage"),
    (r"\bcar rental|automobile rental\b", "Voyage"),
    (r"\btravel agen|cruise|railroad|passenger\b", "Voyage"),
    (r"\btaxi|limousine|rideshare|bus line|commuter\b", "Transport Local"),
    (r"\brestaurant|eating place|caterer\b", "Repas Client"),
    (r"\bfast food|bakeries|bar\b|cocktail", "Repas Personnel"),
    (r"\bsoftware|computer programming|data processing|information retrieval\b", "Logiciel / IT"),
    (r"\bcomputer|electronics\b", "Logiciel / IT"),
    (r"\bservice station|fuel|gasoline|petroleum\b", "Carburant"),
    (r"\bstationery|office.*suppl|school suppl\b", "Fournitures de bureau"),
    (r"\btelecommunication|telephone|cable\b", "Télécommunications"),
]


def _normalize_mcc(value: Any) -> str | None:
    if pd.isna(value):
        return None
    s = re.sub(r"\D", "", str(value).strip())
    return s.zfill(4) if s else None


def build_mcc_category_map(mcc_codes_path: str) -> dict[str, str]:
    df = pd.read_csv(mcc_codes_path, dtype=str).fillna("")
    desc_col = "edited_description" if "edited_description" in df.columns else df.columns[1]
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        mcc = _normalize_mcc(row.get("mcc"))
        if mcc:
            out[mcc] = _resolve_category(mcc, str(row.get(desc_col, "")))
    return out


def _resolve_category(mcc: str, description: str) -> str:
    if mcc in MCC_OVERRIDES:
        return MCC_OVERRIDES[mcc]
    text = description.lower()
    for pattern, category in KEYWORD_RULES:
        if re.search(pattern, text):
            return category
    try:
        code = int(mcc)
    except ValueError:
        return DEFAULT_BRIM_CATEGORY
    if 3000 <= code <= 3999:   # airlines / car rental / lodging
        return "Voyage"
    return DEFAULT_BRIM_CATEGORY


# =========================================================================== #
# Load transactions (+ attribution, flags, strikes)
# =========================================================================== #

def _parse_date(s: Any):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def load_transactions(path: str, cat_map: dict[str, str],
                      employees_path: str | None, departments_path: str | None) -> pd.DataFrame:
    """Read the Supabase-shaped transactions table and map MCC -> Brim category."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["id"] = df["id"].astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0).round(2)  # already CAD
    df["_mcc"] = df["merchant_category"].apply(_normalize_mcc)
    df["brim_category"] = df["_mcc"].map(cat_map).fillna(DEFAULT_BRIM_CATEGORY)

    # Optional attribution: employee_id -> employees -> departments
    df["employee_name"] = None
    df["department"] = None
    if employees_path:
        emp = pd.read_csv(employees_path, encoding="utf-8-sig")
        parts = [c for c in ("first_name", "last_name") if c in emp.columns]
        if parts:
            emp["employee_name"] = emp[parts].fillna("").agg(" ".join, axis=1).str.strip()
        if departments_path and "department_id" in emp.columns:
            dept = pd.read_csv(departments_path, encoding="utf-8-sig")
            if {"id", "department_name"}.issubset(dept.columns):
                emp = emp.merge(dept.rename(columns={"id": "department_id", "department_name": "department"}),
                                on="department_id", how="left")
        keep = ["id"] + [c for c in ("employee_name", "department") if c in emp.columns]
        df = df.drop(columns=["employee_name", "department"]).merge(
            emp[keep].rename(columns={"id": "employee_id"}), on="employee_id", how="left")
    return df


def load_flags(path: str | None) -> dict[str, list[dict]]:
    """transaction_flags -> {transaction_id: [ {warning_message, weight}, ... ]}."""
    flags: dict[str, list[dict]] = defaultdict(list)
    if not path:
        return flags
    df = pd.read_csv(path, encoding="utf-8-sig")
    for _, r in df.iterrows():
        tid = str(r["transaction_id"])
        flags[tid].append({
            "warning_message": str(r.get("warning_message", "")),
            "weight": float(pd.to_numeric(r.get("weight"), errors="coerce") or 0.0),
        })
    return flags


def load_strikes(path: str | None) -> dict[str, dict]:
    """employee_strikes -> {employee_id: {count, total_cheated, descriptions[]}}."""
    out: dict[str, dict] = {}
    if not path:
        return out
    df = pd.read_csv(path, encoding="utf-8-sig")
    for emp, g in df.groupby("employee_id"):
        out[str(emp)] = {
            "count": int(len(g)),
            "total_cheated": round(float(pd.to_numeric(g.get("amount_cheated"), errors="coerce").fillna(0).sum()), 2),
            "descriptions": [str(x) for x in g.get("strike_description", pd.Series([])).tolist()][:5],
        }
    return out


# =========================================================================== #
# Grouping: deterministic spatiotemporal clustering + LLM labeling  -> event_group_id
# =========================================================================== #

def _norm_city(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _haversine_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float | None:
    try:
        lat1, lon1, lat2, lon2 = (float(lat1), float(lon1), float(lat2), float(lon2))
    except (TypeError, ValueError):
        return None
    if any(pd.isna(x) for x in (lat1, lon1, lat2, lon2)):
        return None
    r = 6371.0  # Earth radius (km)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _same_place(a: Any, b: Any) -> bool:
    """Same city (normalized string) or geo-coordinates within GEO_SAME_KM."""
    ca, cb = _norm_city(a.get("city")), _norm_city(b.get("city"))
    if ca and cb:
        return ca == cb
    dist = _haversine_km(a.get("latitude"), a.get("longitude"),
                         b.get("latitude"), b.get("longitude"))
    return dist is not None and dist <= GEO_SAME_KM


def cluster_transactions(df: pd.DataFrame, gap_days: int) -> list[pd.DataFrame]:
    """Per employee, sort by date, then split into events spatiotemporally.

    A new cluster starts when the date gap from the previous transaction exceeds
    `gap_days` — but if the two transactions are in the *same place* (same city, or
    coordinates within GEO_SAME_KM), we tolerate `SAME_PLACE_GAP_BONUS` extra days.
    This keeps a single trip (e.g. a San Diego conference spanning a weekend) together
    while still splitting genuinely separate events.
    """
    clusters: list[pd.DataFrame] = []
    for _emp, g in df.groupby("employee_id", dropna=False):
        g = g.assign(_d=g["date"].map(_parse_date)).sort_values("_d", na_position="last")
        current_idx: list[int] = []
        prev_date = None
        prev_row = None
        for idx, row in g.iterrows():
            d = row["_d"]
            if current_idx and prev_date is not None and d is not None:
                threshold = gap_days + (SAME_PLACE_GAP_BONUS if _same_place(prev_row, row) else 0)
                if (d - prev_date).days > threshold:
                    clusters.append(df.loc[current_idx])
                    current_idx = []
            current_idx.append(idx)
            prev_date = d if d is not None else prev_date
            prev_row = row
        if current_idx:
            clusters.append(df.loc[current_idx])
    return clusters


def _cluster_summary(c: pd.DataFrame) -> dict:
    cats: dict[str, float] = defaultdict(float)
    for _, r in c.iterrows():
        cats[r["brim_category"]] += r["amount"]
    dates = [d for d in c["date"].map(_parse_date) if d]
    return {
        "merchants": sorted(c["merchant_name"].dropna().astype(str).unique())[:8],
        "cities": sorted(c["city"].dropna().astype(str).unique())[:5],
        "categories": {k: round(v, 2) for k, v in cats.items()},
        "date_from": min(dates).strftime("%Y-%m-%d") if dates else "",
        "date_to": max(dates).strftime("%Y-%m-%d") if dates else "",
        "n": int(len(c)),
    }


def _label_mock(multi: list[pd.DataFrame]) -> list[dict]:
    labels = []
    for c in multi:
        s = _cluster_summary(c)
        top = max(s["categories"], key=s["categories"].get) if s["categories"] else "Dépenses"
        where = s["cities"][0].title() if s["cities"] else ""
        labels.append({
            "title": f"{top}{' — ' + where if where else ''} ({s['date_from']}…{s['date_to']})",
            "reasoning": f"{s['n']} transactions du même employé en quelques jours.",
        })
    return labels


def _label_llm(multi: list[pd.DataFrame]) -> list[dict]:
    from langchain_core.prompts import ChatPromptTemplate
    from pydantic import BaseModel, Field

    class Label(BaseModel):
        index: int = Field(description="cluster index")
        title: str = Field(description="concise event title, e.g. 'Fuel & permits — Iowa run'")
        reasoning: str = Field(description="one sentence on what this group represents")

    class Labels(BaseModel):
        labels: list[Label]

    chain = ChatPromptTemplate.from_messages([
        ("system", "You name corporate expense events. Each item is one employee's cluster of "
                   "transactions close in time. Give a concise, specific title and one-sentence "
                   "reasoning. Echo back the index."),
        ("human", "Clusters:\n{clusters}\n\nLabel all {n}."),
    ]) | make_chat_llm().with_structured_output(Labels)

    out: list[dict | None] = [None] * len(multi)
    for start in range(0, len(multi), LABEL_BATCH_SIZE):
        batch = multi[start:start + LABEL_BATCH_SIZE]
        payload = [{"index": start + i, **_cluster_summary(c)} for i, c in enumerate(batch)]
        res = chain.invoke({"clusters": json.dumps(payload, ensure_ascii=False), "n": len(batch)})
        for lab in res.labels:
            if 0 <= lab.index < len(out):
                out[lab.index] = {"title": lab.title, "reasoning": lab.reasoning}
    fb = _label_mock(multi)
    return [out[i] or fb[i] for i in range(len(multi))]


# =========================================================================== #
# AI approval recommendation (reasons over flags + strike history)
# =========================================================================== #

RECO_SYSTEM = """You are an AI expense-approval assistant for a corporate finance team.
Given one expense report — its transactions, category totals, policy warnings (from the
compliance engine, each with a severity weight), and the employee's strike history —
recommend one of: "approve", "review", or "deny" for the CFO.
- approve: clearly within policy, no material warnings.
- review: needs a human look (large amount, partial context, low-weight warnings).
- deny: clear violation (high-weight warnings, or a repeat offender with prior strikes).
Reference the actual numbers, warnings, and strike history. Be concise."""

RECO_HUMAN = """Reports (JSON array). Return one recommendation per report, echoing report_id.

{reports_json}

Recommend for all {n}."""


def _reco_schema():
    from pydantic import BaseModel, Field

    class Reco(BaseModel):
        report_id: str
        recommendation: str = Field(description='"approve" | "review" | "deny"')
        reasoning: str = Field(description="1-2 sentences referencing numbers/warnings/strikes")

    class Batch(BaseModel):
        recommendations: list[Reco]

    return Batch


def _needs_judgment(r: dict) -> bool:
    # Repeat offenders (any strike history) always get scrutiny, even on small amounts.
    return bool(r["_flags"]) or bool(r["_strikes"]) or r["total_amount"] > AUTO_APPROVE_MAX_CAD or r["_n"] > 1


def recommend(reports: list[dict], use_llm: bool) -> None:
    judged = [r for r in reports if _needs_judgment(r)]
    trivial = [r for r in reports if not _needs_judgment(r)]
    for r in trivial:
        r["ai_recommendation"] = "approve"
        r["ai_reasoning"] = f"Auto-approved: ${r['total_amount']:.2f} CAD, single low-value item, no warnings."

    if judged and use_llm:
        from langchain_core.prompts import ChatPromptTemplate
        chain = ChatPromptTemplate.from_messages(
            [("system", RECO_SYSTEM), ("human", RECO_HUMAN)]
        ) | make_chat_llm().with_structured_output(_reco_schema())
        by_id: dict[str, Any] = {}
        for start in range(0, len(judged), RECO_BATCH_SIZE):  # batch so big runs don't blow context
            batch = judged[start:start + RECO_BATCH_SIZE]
            slim = [{
                "report_id": r["id"], "title": r["title"], "employee": r["_employee_name"],
                "department": r["_department"], "total_amount_cad": r["total_amount"],
                "categories": r["_categories"], "warnings": r["_flags"], "strike_history": r["_strikes"],
            } for r in batch]
            res = chain.invoke({"reports_json": json.dumps(slim, ensure_ascii=False), "n": len(batch)})
            by_id.update({x.report_id: x for x in res.recommendations})
        for r in judged:
            x = by_id.get(r["id"])
            r["ai_recommendation"] = x.recommendation if x else "review"
            r["ai_reasoning"] = x.reasoning if x else "No recommendation returned."
    else:
        for r in judged:  # deterministic fallback
            max_w = max((f["weight"] for f in r["_flags"]), default=0)
            strikes = r["_strikes"]["count"] if r["_strikes"] else 0
            if r["_flags"] and (max_w >= 0.66 or strikes >= 2):
                dec = "deny"
            elif r["_flags"] or r["total_amount"] > 500:
                dec = "review"
            else:
                dec = "approve"
            r["ai_recommendation"] = dec
            r["ai_reasoning"] = (f"${r['total_amount']:.2f} CAD, {len(r['_flags'])} warning(s) "
                                 f"(max weight {max_w}), {strikes} prior strike(s).")

    print(f"[reco: {len(judged)} judged, {len(trivial)} auto-approved]", file=sys.stderr)


# =========================================================================== #
# Build expense_reports + event_group_id assignments
# =========================================================================== #

def build_reports(df: pd.DataFrame, gap_days: int, flags: dict, strikes: dict,
                  use_llm: bool) -> tuple[list[dict], list[dict]]:
    clusters = cluster_transactions(df, gap_days)
    multi = [c for c in clusters if len(c) > 1]
    labels = (_label_llm(multi) if use_llm and multi else _label_mock(multi)) if multi else []

    assignments: list[dict] = []   # {transaction_id, event_group_id}
    reports: list[dict] = []
    li = iter(labels)
    for c in clusters:
        group_id = uuid.uuid4().hex
        for tid in c["id"]:
            assignments.append({"transaction_id": str(tid), "event_group_id": group_id})

        if len(c) > 1:
            lab = next(li)
            title, reasoning = lab["title"], lab["reasoning"]
        else:
            row = c.iloc[0]
            title = f"{row['merchant_name']} ({row['brim_category']})"
            reasoning = "Transaction isolée."

        dates = [d for d in c["date"].map(_parse_date) if d]
        emp_ids = [str(x) for x in c["employee_id"].dropna().unique()]
        cats: dict[str, float] = defaultdict(float)
        for _, r in c.iterrows():
            cats[r["brim_category"]] += r["amount"]
        report_flags = [
            {"transaction_id": str(tid), **f}
            for tid in c["id"] for f in flags.get(str(tid), [])
        ]
        emp_strikes = strikes.get(emp_ids[0]) if emp_ids else None

        reports.append({
            # ---- columns that map straight to the expense_reports table ----
            "id": uuid.uuid4().hex,
            "employee_id": emp_ids[0] if emp_ids else None,
            "event_group_id": group_id,
            "title": title,
            "date_from": min(dates).strftime("%Y-%m-%d") if dates else None,
            "date_to": max(dates).strftime("%Y-%m-%d") if dates else None,
            "total_amount": round(float(c["amount"].sum()), 2),
            "status": "ready_for_approval",
            "pdf_url": None,
            "ai_recommendation": None,   # filled by recommend()
            "ai_reasoning": None,
            # ---- internal context (prefixed _, not written to DB) ----
            "_grouping_reasoning": reasoning,
            "_n": int(len(c)),
            "_employee_name": (c["employee_name"].dropna().iloc[0] if c["employee_name"].notna().any() else None),
            "_department": (c["department"].dropna().iloc[0] if c["department"].notna().any() else None),
            "_categories": {k: round(v, 2) for k, v in cats.items()},
            "_flags": report_flags,
            "_strikes": emp_strikes,
        })

    recommend(reports, use_llm)
    return assignments, reports


# =========================================================================== #
# Runner
# =========================================================================== #

def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Feature 4 — Automated Expense Report Generation.")
    ap.add_argument("--transactions", required=True, help="transactions CSV (Supabase shape).")
    ap.add_argument("--mcc", default="mcc_codes.csv")
    ap.add_argument("--flags", default=None, help="transaction_flags CSV (optional).")
    ap.add_argument("--strikes", default=None, help="employee_strikes CSV (optional).")
    ap.add_argument("--employees", default=None)
    ap.add_argument("--departments", default=None)
    ap.add_argument("--model", default=None, help="Gemini model id (default gemini-2.5-flash).")
    ap.add_argument("--gap-days", type=int, default=GROUP_GAP_DAYS)
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N transactions.")
    ap.add_argument("--mock-llm", action="store_true", help="No API calls.")
    ap.add_argument("--out", default=None, help="Write JSON here (default stdout).")
    ap.add_argument("--keep-context", action="store_true", help="Keep internal _-prefixed fields in output.")
    args = ap.parse_args()
    if args.model:
        os.environ["GEMINI_MODEL"] = args.model

    cat_map = build_mcc_category_map(args.mcc)
    df = load_transactions(args.transactions, cat_map, args.employees, args.departments)
    if args.limit is not None and args.limit < len(df):
        df = df.head(args.limit)
        print(f"[limited to first {args.limit} transactions]", file=sys.stderr)
    flags = load_flags(args.flags)
    strikes = load_strikes(args.strikes)

    use_llm = not args.mock_llm
    try:
        assignments, reports = build_reports(df, args.gap_days, flags, strikes, use_llm)
        mode = (get_model() if use_llm else "mock")
    except Exception as exc:  # noqa: BLE001 — never hard-fail; degrade to deterministic
        print(f"[LLM unavailable: {exc}] -> deterministic fallback", file=sys.stderr)
        assignments, reports = build_reports(df, args.gap_days, flags, strikes, use_llm=False)
        mode = "mock (fallback)"

    if not args.keep_context:
        reports = [{k: v for k, v in r.items() if not k.startswith("_")} for r in reports]

    output = {
        "feature": "4 - Automated Expense Report Generation",
        "model": mode,
        "transaction_count": int(len(df)),
        "report_count": len(reports),
        "transaction_event_groups": assignments,   # -> UPDATE transactions SET event_group_id
        "expense_reports": reports,                 # -> INSERT INTO expense_reports
    }
    payload = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"[wrote {len(reports)} reports + {len(assignments)} group assignments -> {args.out}]", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
