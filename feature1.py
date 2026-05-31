"""
Feature 1 — Talk to Your Data (Brim Assistant engine)
=====================================================
Agentic text-to-SQL analytics over the SMB transaction data. A finance manager asks in
plain English; the engine PLANS a SQL query, GUARDS it (read-only), EXECUTES it against
DuckDB so the numbers come from real aggregation (not the LLM), SELF-REPAIRS on error,
then NARRATES the result and picks a visualization.

Interaction model: always free-text. Follow-up *choices* (`followUpSuggestions`) come
from a battle-tested capability registry — every chip maps to a known-good query, so a
suggested chip can never be unanswerable, while typing stays unrestricted.

Mirrors the other engines: reuses feature4's loaders / MCC category map / LLM factory,
Supabase-shaped CSV inputs, --mock-llm + graceful degradation (never hard-fails).

  INPUTS (CSV mirrors; only `transactions` required — the more you give, the more it answers):
    transactions, employees, departments, budgets, mcc_codes,
    transaction_flags, employee_strikes

  OUTPUT (JSON — the /api/assistant contract in backend.md):
    {
      "text": "...",                                         # narrative answer
      "visualization": { "type": "bar|line|pie|table|kpi", "title": "...", "data": [...] },
      "followUpSuggestions": ["...", ...],                   # chips from the capability registry
      "sql": "..."                                           # the query that produced the answer
    }

Usage:
    py feature1.py --transactions transactions.csv --question "Top merchants this month"
    py feature1.py --transactions transactions.csv --employees employees.csv \
        --departments departments.csv --budgets budgets.csv --flags transaction_flags.csv \
        --strikes employee_strikes.csv --question "Who has the most flags?"
    py feature1.py --transactions transactions.csv --question "..." --mock-llm   # no API calls
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import duckdb
import pandas as pd

# Single source of truth: reuse Feature 4's loaders / category map / LLM factory.
from feature4 import build_mcc_category_map, load_transactions, make_chat_llm


# =========================================================================== #
# Config
# =========================================================================== #

MAX_ROWS = 200          # LIMIT injected into any query that lacks one
REPAIR_RETRIES = 2      # self-correction attempts when generated SQL errors
CHART_TYPES = ("bar", "line", "pie", "table", "kpi")
BRIM_CATEGORIES = [
    "Repas Client", "Repas Personnel", "Voyage", "Transport Local", "Logiciel / IT",
    "Carburant", "Fournitures de bureau", "Télécommunications", "Autre",
]
# natural-language hints -> Brim spend category (so "software" hits 'Logiciel / IT')
CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    (r"software|logiciel|saas|subscription|it\b", "Logiciel / IT"),
    (r"travel|flight|hotel|airfare|voyage|trip", "Voyage"),
    (r"taxi|uber|rideshare|transit|transport", "Transport Local"),
    (r"client meal|team (?:dinner|lunch|meal)|repas client", "Repas Client"),
    (r"meal|dinner|lunch|restaurant|food|repas", "Repas Personnel"),
    (r"fuel|gas|gasoline|carburant", "Carburant"),
    (r"office|supplies|stationery|fourniture", "Fournitures de bureau"),
    (r"phone|telecom|internet|télécom", "Télécommunications"),
]


# =========================================================================== #
# Capability registry — the battle-tested chips. Each maps to a known-good query
# pattern; followUpSuggestions are drawn ONLY from here, so a chip is always answerable.
# =========================================================================== #

CAPABILITIES: list[dict] = [
    {"id": "spend_by_dept_cat", "chip": "Spend by department & category", "needs": ["tx"],
     "kw": r"spend|spent|category|software|travel|meal"},
    {"id": "compare_depts", "chip": "Compare two departments", "needs": ["tx"],
     "kw": r"compare|versus|\bvs\b|difference"},
    {"id": "top_merchants", "chip": "Top merchants", "needs": ["tx"],
     "kw": r"merchant|vendor|supplier|top"},
    {"id": "spend_trend", "chip": "Monthly spend trend", "needs": ["tx"],
     "kw": r"trend|over time|month|monthly|grow"},
    {"id": "budget_status", "chip": "Departments over budget", "needs": ["budget"],
     "kw": r"budget|over budget|remaining|overspend"},
    {"id": "most_flagged", "chip": "Employees with the most flags", "needs": ["flags"],
     "kw": r"flag|violation|policy|risky"},
    {"id": "repeat_offenders", "chip": "Repeat offenders (2+ strikes)", "needs": ["strikes"],
     "kw": r"strike|offender|repeat|fraud"},
    {"id": "split_attempts", "chip": "Split-purchase attempts", "needs": ["flags"],
     "kw": r"split|circumvent|dodge|threshold"},
]


def available_capabilities(present: set[str]) -> list[dict]:
    return [c for c in CAPABILITIES if set(c["needs"]).issubset(present)]


def suggest_chips(question: str, present: set[str], answered_id: str | None) -> list[str]:
    """Rank available capabilities by keyword relevance to the question; never repeat
    the one just answered. Deterministic -> chips are guaranteed answerable."""
    q = question.lower()
    caps = [c for c in available_capabilities(present) if c["id"] != answered_id]
    scored = sorted(caps, key=lambda c: (bool(re.search(c["kw"], q)), c["id"]), reverse=True)
    return [c["chip"] for c in scored[:3]]


# =========================================================================== #
# Data layer: load the CSV mirrors into an in-memory DuckDB
# =========================================================================== #

def build_db(args) -> tuple[duckdb.DuckDBPyConnection, set[str]]:
    cat_map = build_mcc_category_map(args.mcc)
    tx = load_transactions(args.transactions, cat_map, args.employees, args.departments)
    if args.limit is not None and args.limit < len(tx):
        tx = tx.head(args.limit)

    con = duckdb.connect()
    con.register("_tx_df", tx)
    # cast date to TIMESTAMP so date_trunc/quarter/year work; keep all other columns
    con.execute("CREATE TABLE tx AS SELECT * REPLACE (TRY_CAST(date AS TIMESTAMP) AS date) FROM _tx_df")
    con.unregister("_tx_df")
    con.execute("CREATE VIEW emp AS SELECT DISTINCT employee_id, employee_name, department FROM tx")
    present = {"tx", "emp"}

    if args.flags:
        con.register("_f", pd.read_csv(args.flags, encoding="utf-8-sig"))
        con.execute("CREATE TABLE flags AS SELECT * FROM _f"); con.unregister("_f")
        present.add("flags")
    if args.strikes:
        con.register("_s", pd.read_csv(args.strikes, encoding="utf-8-sig"))
        con.execute("CREATE TABLE strikes AS SELECT * FROM _s"); con.unregister("_s")
        present.add("strikes")
    if args.budgets:
        con.register("_b", pd.read_csv(args.budgets, encoding="utf-8-sig"))
        if args.departments:
            con.register("_d", pd.read_csv(args.departments, encoding="utf-8-sig"))
            con.execute("""CREATE TABLE budget AS
                SELECT d.department_name AS department, b.budget, b.quarter, b.year
                FROM _b b LEFT JOIN _d d ON b.department_id = d.id""")
            con.unregister("_d")
        else:
            con.execute("CREATE TABLE budget AS SELECT department_id AS department, budget, quarter, year FROM _b")
        con.unregister("_b")
        present.add("budget")
    return con, present


def schema_doc(present: set[str]) -> str:
    parts = ["tx(id, employee_id, date TIMESTAMP, amount DOUBLE /*CAD*/, merchant_name, "
             "merchant_category /*MCC*/, city, zipcode, latitude, longitude, event_group_id, "
             "status, brim_category, employee_name, department)"]
    if "budget" in present:
        parts.append("budget(department, budget DOUBLE, quarter /*'Q1'..'Q4'*/, year INT)")
    if "flags" in present:
        parts.append("flags(transaction_id, warning_message, weight /*1..5 severity*/)")
    if "strikes" in present:
        parts.append("strikes(employee_id, strike_description, strike_date, amount_cheated)")
    notes = ("Notes: money is CAD. brim_category ∈ {" + ", ".join(BRIM_CATEGORIES) + "}; "
             "'software' = 'Logiciel / IT'. Join flags via flags.transaction_id = tx.id; "
             "strikes via strikes.employee_id = tx.employee_id (or emp). Use DuckDB date "
             "functions (date_trunc, quarter(date), year(date)).")
    return "Tables:\n  " + "\n  ".join(parts) + "\n" + notes


# =========================================================================== #
# SQL guard + execution with self-repair
# =========================================================================== #

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|copy|pragma|replace)\b", re.I)


def guard_sql(sql: str) -> str:
    """Accept a single read-only SELECT/WITH; reject everything else; inject a LIMIT."""
    s = sql.strip()
    s = re.sub(r"^```(?:sql)?|```$", "", s, flags=re.I | re.M).strip()
    s = s.rstrip(";").strip()
    if ";" in s:
        raise ValueError("only a single statement is allowed")
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValueError("only SELECT/WITH queries are allowed")
    if _FORBIDDEN.search(s):
        raise ValueError("write/DDL keywords are not allowed")
    if not re.search(r"\blimit\b", low):
        s += f" LIMIT {MAX_ROWS}"
    return s


def execute_with_repair(con, sql: str, repair) -> tuple[pd.DataFrame | None, str, str | None]:
    """Run the query; on error optionally ask `repair(sql, error)` for a fix, up to N times."""
    last_err = None
    for attempt in range(REPAIR_RETRIES + 1):
        try:
            safe = guard_sql(sql)
            return con.execute(safe).fetchdf(), safe, None
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if repair is None or attempt == REPAIR_RETRIES:
                break
            try:
                sql = repair(sql, last_err)
            except Exception as rexc:  # noqa: BLE001 — repair itself failed; stop
                last_err = f"{last_err} | repair failed: {rexc}"
                break
    return None, sql, last_err


# =========================================================================== #
# LLM steps: plan (NL -> SQL), repair (SQL + error -> SQL), narrate (rows -> text)
# =========================================================================== #

def _plan_schema():
    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        sql: str = Field(description="one read-only DuckDB SELECT answering the question")
        chart: str = Field(description="bar | line | pie | table | kpi")
        title: str = Field(description="short chart/answer title")

    return Plan


PLAN_SYSTEM = """You translate a finance manager's question into ONE read-only DuckDB SQL
query over the schema below. Use only the listed tables/columns. Money is CAD. Prefer
GROUP BY for breakdowns, ROUND(SUM(amount),2) for totals, and a single KPI value when the
question asks for one number. Choose the best chart: kpi (one number), line (time series),
bar (category comparison), pie (share of a whole), table (detail rows). Never write to the DB.

{schema}

Conversation so far (for follow-ups; resolve pronouns/comparisons against it):
{history}"""

NARRATE_SYSTEM = """You are a finance analytics assistant. Given the question and the query
result rows (JSON), write a concise 1-3 sentence answer for a non-technical finance manager.
Reference the actual numbers. Do not invent data beyond the rows. No preamble."""


def make_llm_steps(schema: str, history: str):
    from langchain_core.prompts import ChatPromptTemplate

    plan_chain = ChatPromptTemplate.from_messages(
        [("system", PLAN_SYSTEM), ("human", "{question}")]
    ) | make_chat_llm().with_structured_output(_plan_schema())

    repair_chain = ChatPromptTemplate.from_messages([
        ("system", "Fix this DuckDB SQL. Return ONLY the corrected single SELECT.\n\n" + schema),
        ("human", "Question: {question}\nSQL:\n{sql}\nError: {error}"),
    ]) | make_chat_llm()

    narrate_chain = ChatPromptTemplate.from_messages(
        [("system", NARRATE_SYSTEM), ("human", "Question: {question}\nRows: {rows}")]
    ) | make_chat_llm()

    def plan(question: str) -> dict:
        p = plan_chain.invoke({"schema": schema, "history": history or "(none)", "question": question})
        chart = p.chart if p.chart in CHART_TYPES else "table"
        return {"sql": p.sql, "chart": chart, "title": p.title}

    def repair(question: str):
        def _r(sql: str, error: str) -> str:
            return guard_sql(repair_chain.invoke({"question": question, "sql": sql, "error": error}).content)
        return _r

    def narrate(question: str, rows: list[dict]) -> str:
        return narrate_chain.invoke({"question": question, "rows": json.dumps(rows, default=str)[:6000]}).content.strip()

    return plan, repair, narrate


# =========================================================================== #
# Deterministic mock planner/narrator (so --mock-llm demos without an API key)
# =========================================================================== #

def _match_department(question: str, con) -> str | None:
    q = question.lower()
    for (dept,) in con.execute("SELECT DISTINCT department FROM tx WHERE department IS NOT NULL").fetchall():
        if dept and dept.lower() in q:
            return dept
    return None


def _match_category(question: str) -> str | None:
    q = question.lower()
    for cat in BRIM_CATEGORIES:
        if cat.lower() in q:
            return cat
    for pattern, cat in CATEGORY_KEYWORDS:
        if re.search(pattern, q):
            return cat
    return None


def _period_clause(question: str) -> str:
    """A small set of relative periods, computed off the latest transaction date."""
    q = question.lower()
    mx = "(SELECT max(date) FROM tx)"
    if "last quarter" in q:
        return (f"date >= date_trunc('quarter', {mx}) - INTERVAL 3 MONTH "
                f"AND date < date_trunc('quarter', {mx})")
    if "this quarter" in q or "quarter" in q:
        return f"date >= date_trunc('quarter', {mx})"
    if "last month" in q:
        return (f"date >= date_trunc('month', {mx}) - INTERVAL 1 MONTH "
                f"AND date < date_trunc('month', {mx})")
    if "this month" in q or "month" in q:
        return f"date >= date_trunc('month', {mx})"
    if "this year" in q or "ytd" in q:
        return f"year(date) = year({mx})"
    return ""


def mock_plan(question: str, present: set[str], con) -> dict:
    q = question.lower()
    period = _period_clause(question)
    where = (" WHERE " + period) if period else ""

    if "split" in q and "flags" in present:
        return {"id": "split_attempts", "chart": "table", "title": "Split-purchase attempts",
                "sql": "SELECT t.employee_name, t.merchant_name, t.amount, f.warning_message "
                       "FROM flags f JOIN tx t ON f.transaction_id = t.id WHERE f.weight = 5"}
    if re.search(r"strike|offender|repeat", q) and "strikes" in present:
        return {"id": "repeat_offenders", "chart": "bar", "title": "Repeat offenders (2+ strikes)",
                "sql": "SELECT e.employee_name, COUNT(*) AS strikes, ROUND(SUM(s.amount_cheated),2) AS amount "
                       "FROM strikes s LEFT JOIN emp e ON s.employee_id = e.employee_id "
                       "GROUP BY e.employee_name HAVING COUNT(*) >= 2 ORDER BY strikes DESC"}
    if re.search(r"flag|violation|policy", q) and "flags" in present:
        return {"id": "most_flagged", "chart": "bar", "title": "Employees with the most flags",
                "sql": "SELECT t.employee_name, COUNT(*) AS flags, ROUND(AVG(f.weight),1) AS avg_severity "
                       "FROM flags f JOIN tx t ON f.transaction_id = t.id "
                       "GROUP BY t.employee_name ORDER BY flags DESC"}
    if "budget" in q and "budget" in present:
        return {"id": "budget_status", "chart": "table", "title": "Budget status by department",
                "sql": "SELECT b.department, b.budget, ROUND(SUM(t.amount),2) AS spent, "
                       "ROUND(b.budget - SUM(t.amount),2) AS remaining "
                       "FROM budget b LEFT JOIN tx t ON t.department = b.department "
                       "AND b.year = year(t.date) AND b.quarter = 'Q' || quarter(t.date) "
                       "GROUP BY b.department, b.budget ORDER BY remaining ASC"}
    if re.search(r"merchant|vendor|supplier", q):
        return {"id": "top_merchants", "chart": "bar", "title": "Top merchants",
                "sql": f"SELECT merchant_name, ROUND(SUM(amount),2) AS total, COUNT(*) AS n "
                       f"FROM tx{where} GROUP BY merchant_name ORDER BY total DESC LIMIT 5"}
    if re.search(r"trend|over time|monthly|by month", q):
        return {"id": "spend_trend", "chart": "line", "title": "Monthly spend",
                "sql": "SELECT date_trunc('month', date) AS month, ROUND(SUM(amount),2) AS total "
                       "FROM tx GROUP BY month ORDER BY month"}
    if re.search(r"compare|versus|\bvs\b", q):
        cat = _match_category(question)
        cat_w = f" WHERE brim_category = '{cat}'" if cat else ""
        return {"id": "compare_depts", "chart": "bar",
                "title": f"Department comparison{(' — ' + cat) if cat else ''}",
                "sql": f"SELECT department, ROUND(SUM(amount),2) AS total FROM tx{cat_w} "
                       f"GROUP BY department ORDER BY total DESC"}

    # default: spend by department & category, honoring any department/category/period filter
    dept = _match_department(question, con)
    cat = _match_category(question)
    clauses = [c for c in (period,
                           f"department = '{dept}'" if dept else "",
                           f"brim_category = '{cat}'" if cat else "") if c]
    w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    single = bool(dept and cat)
    return {"id": "spend_by_dept_cat", "chart": "kpi" if single else "bar",
            "title": f"Spend{(' — ' + dept) if dept else ''}{(' / ' + cat) if cat else ' by department'}",
            "sql": (f"SELECT ROUND(SUM(amount),2) AS total FROM tx{w}" if single
                    else f"SELECT department, ROUND(SUM(amount),2) AS total FROM tx{w} "
                         f"GROUP BY department ORDER BY total DESC")}


def mock_narrate(question: str, df: pd.DataFrame, plan: dict) -> str:
    if df is None or df.empty:
        return "No matching data for that question."
    if plan["chart"] == "kpi":
        val = df.iloc[0, 0]
        return f"{plan['title']}: ${val:,.2f}." if isinstance(val, (int, float)) else f"{plan['title']}: {val}."
    top = df.iloc[0].to_dict()
    head = ", ".join(f"{k}={v}" for k, v in list(top.items())[:3])
    return f"{len(df)} result(s). Top: {head}."


# =========================================================================== #
# Orchestration
# =========================================================================== #

def _records(df: pd.DataFrame | None) -> list[dict]:
    if df is None or df.empty:
        return []
    out = df.copy()
    for c in out.columns:           # make timestamps JSON-friendly
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].astype(str)
    return json.loads(out.to_json(orient="records"))


def answer(con, present: set[str], question: str, history: str, use_llm: bool) -> dict:
    schema = schema_doc(present)
    answered_id = None

    if use_llm:
        plan_fn, repair_factory, narrate_fn = make_llm_steps(schema, history)
        plan = plan_fn(question)
        df, sql_used, err = execute_with_repair(con, plan["sql"], repair_factory(question))
        text = narrate_fn(question, _records(df)) if err is None else (
            f"I couldn't compute that exactly ({err.splitlines()[0][:120]}). Try one of the suggestions below.")
    else:
        plan = mock_plan(question, present, con)
        answered_id = plan.get("id")
        df, sql_used, err = execute_with_repair(con, plan["sql"], None)
        text = mock_narrate(question, df, plan) if err is None else (
            f"I couldn't compute that exactly. Try one of the suggestions below.")

    chart = plan["chart"] if err is None else "table"
    return {
        "text": text,
        "visualization": {"type": chart, "title": plan["title"], "data": _records(df)},
        "followUpSuggestions": suggest_chips(question, present, answered_id),
        "sql": sql_used,
        "_error": err,
    }


# =========================================================================== #
# Runner
# =========================================================================== #

def _load_history(path: str | None) -> str:
    if not path:
        return ""
    with open(path, encoding="utf-8") as f:
        turns = json.load(f)
    lines = []
    for t in turns[-6:]:
        q = t.get("question", "")
        s = t.get("summary") or t.get("text") or ""
        lines.append(f"Q: {q}\nA: {s}")
    return "\n".join(lines)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Feature 1 — Talk to Your Data (Brim Assistant engine).")
    ap.add_argument("--transactions", required=True, help="transactions CSV (Supabase shape).")
    ap.add_argument("--question", required=True, help="natural-language question.")
    ap.add_argument("--history", default=None, help="JSON file: prior turns [{question, summary}].")
    ap.add_argument("--mcc", default="mcc_codes.csv")
    ap.add_argument("--employees", default=None)
    ap.add_argument("--departments", default=None)
    ap.add_argument("--budgets", default=None)
    ap.add_argument("--flags", default=None)
    ap.add_argument("--strikes", default=None)
    ap.add_argument("--model", default=None, help="Gemini model id (default gemini-2.5-flash).")
    ap.add_argument("--limit", type=int, default=None, help="Only load the first N transactions.")
    ap.add_argument("--mock-llm", action="store_true", help="No API calls (deterministic planner).")
    ap.add_argument("--out", default=None, help="Write JSON here (default stdout).")
    args = ap.parse_args()
    if args.model:
        os.environ["GEMINI_MODEL"] = args.model

    con, present = build_db(args)
    history = _load_history(args.history)

    use_llm = not args.mock_llm
    try:
        result = answer(con, present, args.question, history, use_llm)
        mode = (os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if use_llm else "mock")
    except Exception as exc:  # noqa: BLE001 — never hard-fail; degrade to deterministic
        print(f"[LLM unavailable: {exc}] -> deterministic fallback", file=sys.stderr)
        result = answer(con, present, args.question, history, use_llm=False)
        mode = "mock (fallback)"

    print(f"[assistant: chart={result['visualization']['type']}, "
          f"{len(result['visualization']['data'])} rows, "
          f"{'error' if result.get('_error') else 'ok'}]", file=sys.stderr)

    output = {
        "feature": "1 - Talk to Your Data",
        "model": mode,
        "question": args.question,
        **{k: v for k, v in result.items() if not k.startswith("_")},
    }
    payload = json.dumps(output, indent=2, ensure_ascii=False, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"[wrote answer -> {args.out}]", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
