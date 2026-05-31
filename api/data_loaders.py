"""Shared DataFrame loaders for Supabase tables (no feature3 import)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd


def parse_date(s: Any):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def quarter_of(d: datetime | None) -> str | None:
    if d is None:
        return None
    return f"Q{(d.month - 1) // 3 + 1}"


def year_of(d: datetime | None) -> int | None:
    return d.year if d is not None else None


def normalize_quarter(value: Any) -> str | None:
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


def normalize_transactions_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["id"] = df["id"].astype(str)
    df["employee_id"] = df["employee_id"].astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0).round(2)
    for col in ("merchant_name", "merchant_category", "city", "status"):
        if col not in df.columns:
            df[col] = None
    df["_d"] = df["date"].map(parse_date)
    df["_year"] = df["_d"].map(year_of)
    df["_quarter"] = df["_d"].map(quarter_of)
    return df


def prepare_employees_for_merge(
    emp: pd.DataFrame | None, dept: pd.DataFrame | None
) -> pd.DataFrame | None:
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
                on="department_id",
                how="left",
            )
    keep = ["id"] + [c for c in ("employee_name", "department", "department_id") if c in emp.columns]
    return emp[keep].rename(columns={"id": "employee_id"})


def enrich_transactions(
    df: pd.DataFrame, emp: pd.DataFrame | None, dept: pd.DataFrame | None
) -> pd.DataFrame:
    df = normalize_transactions_columns(df)
    df["employee_name"] = None
    df["department"] = None
    df["department_id"] = None
    emp_merge = prepare_employees_for_merge(emp, dept)
    if emp_merge is not None:
        df = df.drop(
            columns=["employee_name", "department", "department_id"], errors="ignore"
        ).merge(emp_merge, on="employee_id", how="left")
    return df


def flags_from_df(df: pd.DataFrame) -> dict[str, list[dict]]:
    flags: dict[str, list[dict]] = defaultdict(list)
    for _, r in df.iterrows():
        tid = str(r["transaction_id"])
        flags[tid].append({
            "warning_message": str(r.get("warning_message", "")),
            "weight": float(pd.to_numeric(r.get("weight"), errors="coerce") or 0.0),
        })
    return flags


def strikes_from_df(df: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for emp, g in df.groupby("employee_id"):
        out[str(emp)] = {
            "count": int(len(g)),
            "total_cheated": round(
                float(pd.to_numeric(g.get("amount_cheated"), errors="coerce").fillna(0).sum()),
                2,
            ),
            "descriptions": [
                str(x) for x in g.get("strike_description", pd.Series([])).tolist()
            ][:5],
        }
    return out


def budgets_from_df(df: pd.DataFrame) -> dict[tuple[str, str, int], float]:
    out: dict[tuple[str, str, int], float] = {}
    dept_col = (
        "department_id"
        if "department_id" in df.columns
        else ("department" if "department" in df.columns else df.columns[0])
    )
    for _, r in df.iterrows():
        dept = str(r.get(dept_col))
        quarter = normalize_quarter(r.get("quarter"))
        year = pd.to_numeric(r.get("year"), errors="coerce")
        budget = pd.to_numeric(r.get("budget"), errors="coerce")
        if dept and quarter and not pd.isna(year) and not pd.isna(budget):
            out[(dept, quarter, int(year))] = round(float(budget), 2)
    return out
