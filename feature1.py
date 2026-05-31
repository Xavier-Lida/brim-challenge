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

from api.assistant_prompts import build_narrate_system
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

REFUSAL_FR = "Je ne peux répondre qu'aux questions sur vos dépenses et l'utilisation de Brim."
REFUSAL_EN = "I can only answer questions about your spending and how to use Brim."

_OFF_TOPIC_RE = re.compile(
    r"\b(weather|météo|meteo|quel temps|what'?s the weather|how'?s the weather|"
    r"il fait beau|il fait froid|"
    r"recipe|recette|python|javascript|joke|blague|"
    r"football|bitcoin|crypto|poem|poème|horoscope)\b",
    re.I,
)
_DASHBOARD_HELP_RE = re.compile(
    r"\b(where|how do i|how to|comment|où|ou voir|page|sidebar|menu|"
    r"dashboard|navigation|import.*policy|policy import)\b",
    re.I,
)
_ANALYTICS_SIGNAL_RE = re.compile(
    r"\b(spend|spent|total|how many|combien|montant|flag|merchant|budget|"
    r"trend|department|département|quarter|trimestre|month|mois)\b",
    re.I,
)
_AMBIGUOUS_RE = re.compile(r"^compare\??$", re.I)
_CASUAL_CHAT_RE = re.compile(
    r"^(yo[\s!.,]*(ça va|ca va)?|hey|hi|hello|bonjour|salut|coucou|"
    r"ça va|ca va|what'?s up|sup|thanks|thank you|merci)[\s!?.,]*$",
    re.I,
)
_ANALYTICS_INTENT_RE = re.compile(
    r"\b(spend|spent|total|how many|combien|montant|flag|merchant|budget|"
    r"trend|department|département|quarter|trimestre|month|mois|top|list|show|"
    r"who|which|summarize|summary|recent|weekly|daily|compare|versus|vs|"
    r"strike|offender|split|violation|policy|budget|over|meal|travel|software|"
    r"dépense|dépenses|depense|montre|montrez|employé|employe|location|ville)\b",
    re.I,
)


# =========================================================================== #
# Capability registry — the battle-tested chips. Each maps to a known-good query
# pattern; followUpSuggestions are drawn ONLY from here, so a chip is always answerable.
# =========================================================================== #

CAPABILITIES: list[dict] = [
    {"id": "spend_by_dept_cat", "chip": "Spend by department & category", "needs": ["tx"],
     "kw": r"spend|spent|category|software|travel|meal"},
    {"id": "compare_depts", "chip": "Compare two departments", "needs": ["tx"],
     "kw": r"compare|versus|\bvs\b|difference"},
    {"id": "compare_employees", "chip": "Compare two employees", "needs": ["tx"],
     "kw": r"compare|versus|\bvs\b|employee|employé|employe"},
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
    _register_emp_table(con, args.employees, args.departments)
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


def _register_emp_table(
    con: duckdb.DuckDBPyConnection,
    employees_path: str | None,
    departments_path: str | None,
) -> None:
    """Full employee roster in emp when CSV paths are provided; else derive from tx."""
    from api.data_loaders import prepare_employees_for_merge

    if employees_path:
        emp_df = pd.read_csv(employees_path, encoding="utf-8-sig")
        dept_df = (
            pd.read_csv(departments_path, encoding="utf-8-sig")
            if departments_path
            else None
        )
        emp_merge = prepare_employees_for_merge(emp_df, dept_df)
        if emp_merge is not None and not emp_merge.empty:
            con.register("_emp", emp_merge)
            con.execute("CREATE TABLE emp AS SELECT * FROM _emp")
            con.unregister("_emp")
            return
    con.execute(
        "CREATE VIEW emp AS SELECT DISTINCT employee_id, employee_name, department FROM tx"
    )


def build_db_from_supabase(client, limit: int | None = None) -> tuple[duckdb.DuckDBPyConnection, set[str]]:
    """Load Supabase tables into an in-memory DuckDB (same shape as build_db)."""
    from api.data_loaders import prepare_employees_for_merge
    from api.supabase_io import fetch_table, load_transactions_frame

    tx = load_transactions_frame(client)
    if limit is not None and limit < len(tx):
        tx = tx.head(limit)

    con = duckdb.connect()
    con.register("_tx_df", tx)
    con.execute(
        "CREATE TABLE tx AS SELECT * REPLACE (TRY_CAST(date AS TIMESTAMP) AS date) FROM _tx_df"
    )
    con.unregister("_tx_df")

    emp_df = fetch_table(client, "employees")
    dept_df = fetch_table(client, "departments")
    emp_merge = prepare_employees_for_merge(
        emp_df if not emp_df.empty else None,
        dept_df if not dept_df.empty else None,
    )
    if emp_merge is not None and not emp_merge.empty:
        con.register("_emp", emp_merge)
        con.execute("CREATE TABLE emp AS SELECT * FROM _emp")
        con.unregister("_emp")
    else:
        con.execute(
            "CREATE VIEW emp AS SELECT DISTINCT employee_id, employee_name, department FROM tx"
        )
    present = {"tx", "emp"}

    flags_df = fetch_table(client, "transaction_flags")
    if not flags_df.empty:
        con.register("_f", flags_df)
        con.execute("CREATE TABLE flags AS SELECT * FROM _f")
        con.unregister("_f")
        present.add("flags")

    strikes_df = fetch_table(client, "employee_strikes")
    if not strikes_df.empty:
        con.register("_s", strikes_df)
        con.execute("CREATE TABLE strikes AS SELECT * FROM _s")
        con.unregister("_s")
        present.add("strikes")

    budgets_df = fetch_table(client, "budgets")
    if not budgets_df.empty:
        dept_df = fetch_table(client, "departments")
        con.register("_b", budgets_df)
        if not dept_df.empty:
            con.register("_d", dept_df)
            con.execute(
                """CREATE TABLE budget AS
                SELECT d.department_name AS department, b.budget, b.quarter, b.year
                FROM _b b LEFT JOIN _d d ON b.department_id = d.id"""
            )
            con.unregister("_d")
        else:
            con.execute(
                "CREATE TABLE budget AS SELECT department_id AS department, budget, quarter, year FROM _b"
            )
        con.unregister("_b")
        present.add("budget")

    return con, present


def format_history(turns: list[dict]) -> str:
    lines: list[str] = []
    for t in turns[-6:]:
        q = t.get("question", "")
        s = t.get("summary") or t.get("text") or ""
        lines.append(f"Q: {q}\nA: {s}")
    return "\n".join(lines)


def schema_doc(present: set[str]) -> str:
    parts = ["tx(id, employee_id, date TIMESTAMP, amount DOUBLE /*CAD*/, merchant_name, "
             "merchant_category /*MCC*/, city, zipcode, latitude, longitude, event_group_id, "
             "status, brim_category, employee_name, department)"]
    if "emp" in present:
        parts.append(
            "emp(employee_id, employee_name, department) — full roster; "
            "LEFT JOIN tx ON tx.employee_id = emp.employee_id"
        )
    if "budget" in present:
        parts.append("budget(department, budget DOUBLE, quarter /*'Q1'..'Q4'*/, year INT)")
    if "flags" in present:
        parts.append("flags(transaction_id, warning_message, weight /*1..5 severity*/)")
    if "strikes" in present:
        parts.append("strikes(employee_id, strike_description, strike_date, amount_cheated)")
    notes = ("Notes: money is CAD. brim_category ∈ {" + ", ".join(BRIM_CATEGORIES) + "}; "
             "'software' = 'Logiciel / IT'. Join flags via flags.transaction_id = tx.id; "
             "strikes via strikes.employee_id = tx.employee_id (or emp). Use DuckDB date "
             "functions (date_trunc, quarter(date), year(date)). "
             "There is no state column — filter by city ILIKE '%Place%' and/or zipcode for "
             "city/state/region questions (e.g. Illinois, Chicago, Montréal). "
             "Listing or totalling spend for a location is always in scope.")
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


def execute_with_repair(
    con,
    sql: str,
    repair,
    *,
    before_repair=None,
) -> tuple[pd.DataFrame | None, str, str | None]:
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
            if before_repair is not None:
                before_repair()
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
        in_scope: bool = Field(
            description=(
                "False if the question is unrelated to Brim spending, compliance, policy, "
                "budgets, approvals, expense reports, or how to use the Brim dashboard. "
                "True for spend filtered by city, state, region, or zipcode (no state column — use city/zipcode)."
            )
        )
        sql: str = Field(description="one read-only DuckDB SELECT answering the question")
        chart: str = Field(description="bar | line | pie | table | kpi")
        title: str = Field(description="short chart/answer title")

    return Plan


PLAN_SYSTEM = """You translate a finance manager's question into ONE read-only DuckDB SQL
query over the schema below. Use only the listed tables/columns. Money is CAD. Prefer
GROUP BY for breakdowns, ROUND(SUM(amount),2) for totals, and a single KPI value when the
question asks for one number. Choose the best chart: kpi (one number), line (time series),
bar (category comparison), pie (share of a whole), table (detail rows). Never write to the DB.

Scope: set in_scope=false when the question is NOT about company spending analytics,
compliance (flags/strikes), policy/budgets, approvals/reports in the data, or how to use
the Brim dashboard. Employee-vs-employee, department-vs-department, period comparisons,
and location filters (city, state, region, zipcode) are always in_scope. When in_scope=false,
still return a harmless placeholder SQL:
SELECT 'out_of_scope' AS reason LIMIT 1, chart=table, title='Out of scope'.

Location analytics: there is no state column. Map places (Illinois, Texas, Chicago, Montréal,
etc.) to tx.city ILIKE '%Place%' and/or tx.zipcode. Questions like "show all spend in Illinois"
or "list expenses at Chicago" are in_scope — use chart=table with detail rows, not in_scope=false.

When the question is about Brim dashboard navigation only (where to click, which page),
set in_scope=true and use: SELECT 'dashboard_help' AS topic LIMIT 1 with chart=table and
title='Brim dashboard'.

Defaults when the user omits details: current quarter (date >= date_trunc('quarter', max(date)))
for period; ROUND(SUM(amount),2) for spend comparisons. Filter tx.employee_name when two
employees are named or when comparing employees.

{schema}

Conversation so far (for follow-ups; resolve pronouns/comparisons against it):
{history}"""

NARRATE_BASE = """You are a finance analytics assistant. Given the question and the query
result rows (JSON), write a concise 1-3 sentence answer for a non-technical finance manager.
Reference the actual numbers. Do not invent data beyond the rows. No preamble."""


def make_llm_steps(schema: str, history: str):
    from langchain_core.prompts import ChatPromptTemplate

    narrate_system = build_narrate_system(NARRATE_BASE)

    plan_chain = ChatPromptTemplate.from_messages(
        [("system", PLAN_SYSTEM), ("human", "{question}")]
    ) | make_chat_llm().with_structured_output(_plan_schema())

    repair_chain = ChatPromptTemplate.from_messages([
        ("system", "Fix this DuckDB SQL. Return ONLY the corrected single SELECT.\n\n" + schema),
        ("human", "Question: {question}\nSQL:\n{sql}\nError: {error}"),
    ]) | make_chat_llm()

    narrate_chain = ChatPromptTemplate.from_messages(
        [("system", narrate_system), ("human", "Question: {question}\nRows: {rows}")]
    ) | make_chat_llm()

    def plan(question: str) -> dict:
        p = plan_chain.invoke({"schema": schema, "history": history or "(none)", "question": question})
        chart = p.chart if p.chart in CHART_TYPES else "table"
        return {
            "in_scope": p.in_scope,
            "sql": p.sql,
            "chart": chart,
            "title": p.title,
        }

    def repair(question: str):
        def _r(sql: str, error: str) -> str:
            return guard_sql(repair_chain.invoke({"question": question, "sql": sql, "error": error}).content)
        return _r

    def narrate(question: str, rows: list[dict]) -> str:
        return narrate_chain.invoke({"question": question, "rows": json.dumps(rows, default=str)[:6000]}).content.strip()

    def narrate_stream(question: str, rows: list[dict]):
        """Yield narration token-by-token (LangChain streaming) for SSE."""
        payload = {"question": question, "rows": json.dumps(rows, default=str)[:6000]}
        for chunk in narrate_chain.stream(payload):
            piece = getattr(chunk, "content", "")
            if piece:
                yield piece

    return plan, repair, narrate, narrate_stream


# =========================================================================== #
# Scope helpers (off-topic, dashboard help, clarification)
# =========================================================================== #

def _is_french(question: str) -> bool:
    q = question.lower()
    if re.search(r"[àâäéèêëïîôùûüç]", q):
        return True
    return bool(
        re.search(
            r"\b(combien|comment|où|ou|depenses|dépenses|trimestre|mois|approbation|politique|"
            r"quel|quelle|quels|quelles|temps|bonjour|merci|depense|dépense|afficher|montrez)\b",
            q,
            re.I,
        )
    )


def off_topic_refusal(question: str) -> str:
    return REFUSAL_FR if _is_french(question) else REFUSAL_EN


def _is_off_topic(question: str) -> bool:
    q = question.strip()
    if re.search(r"quel temps fait|what'?s the weather|how'?s the weather", q, re.I):
        return True
    return bool(_OFF_TOPIC_RE.search(q))


def _has_analytics_intent(question: str) -> bool:
    return bool(_ANALYTICS_INTENT_RE.search(question))


def _is_casual_chat(question: str) -> bool:
    q = question.strip()
    if not q:
        return True
    return bool(_CASUAL_CHAT_RE.match(q))


def _mock_greeting(question: str) -> str:
    if _is_french(question):
        return (
            "Bonjour — je peux vous aider sur vos dépenses, les signalements ou la policy "
            "chez Northwind Labs. Que souhaitez-vous analyser ?"
        )
    return (
        "Hello — I can help with spend, flags, or policy at Northwind Labs. "
        "What would you like to explore?"
    )


def _format_amount(value: float, *, french: bool) -> str:
    amount = abs(float(value))
    if french:
        whole, cents = f"{amount:.2f}".split(".")
        whole = f"{int(whole):,}".replace(",", " ")
        formatted = f"{whole},{cents} $"
    else:
        formatted = f"${amount:,.2f}"
    if value < 0:
        if french:
            return f"un crédit de {formatted}"
        return f"a credit of {formatted}"
    return formatted


def _human_label(key: str, french: bool) -> str:
    mapping = {
        "department": ("le département", "department"),
        "employee_name": ("l'employé", "employee"),
        "merchant_name": ("le marchand", "merchant"),
        "total": ("le total", "total spend"),
        "spent": ("les dépenses", "spend"),
        "flags": ("les signalements", "flags"),
        "strikes": ("les strikes", "strikes"),
        "avg_severity": ("la gravité moyenne", "average severity"),
        "remaining": ("le reste budgétaire", "remaining budget"),
        "budget": ("le budget", "budget"),
        "month": ("le mois", "month"),
        "n": ("le nombre de transactions", "transaction count"),
    }
    pair = mapping.get(key)
    if pair:
        return pair[0 if french else 1]
    return key.replace("_", " ")


def _narrate_row(row: dict, french: bool) -> str:
    items = list(row.items())
    if not items:
        return ""

    if "department" in row and "total" in row and isinstance(row["total"], (int, float)):
        dept = row["department"]
        amt = _format_amount(float(row["total"]), french=french)
        if french:
            return f"{dept} totalise {amt}"
        return f"{dept} totals {amt}"

    if "employee_name" in row and "flags" in row:
        name = row["employee_name"]
        count = row["flags"]
        if french:
            return f"{name} compte {count} signalements"
        return f"{name} has {count} flags"

    if "employee_name" in row and "strikes" in row:
        name = row["employee_name"]
        count = row["strikes"]
        if french:
            return f"{name} cumule {count} strikes"
        return f"{name} has {count} strikes"

    if "merchant_name" in row and "total" in row and isinstance(row["total"], (int, float)):
        merchant = row["merchant_name"]
        amt = _format_amount(float(row["total"]), french=french)
        if french:
            return f"{merchant} affiche {amt} de dépenses"
        return f"{merchant} shows {amt} in spend"

    parts: list[str] = []
    for key, val in items[:2]:
        label = _human_label(key, french)
        if isinstance(val, float):
            if "amount" in key or "total" in key or "spent" in key or "budget" in key:
                parts.append(f"{label} {_format_amount(val, french=french)}")
            else:
                parts.append(f"{label} {val:.1f}" if val % 1 else f"{label} {int(val)}")
        else:
            parts.append(f"{label} {val}")
    return ", ".join(parts)


def _mock_empty_data(question: str) -> str:
    if _is_french(question):
        return "Je n'ai trouvé aucune donnée correspondant à votre question pour cette période."
    return "I found no data matching your question for this period."


def _narrate_employee_compare(df: pd.DataFrame, question: str) -> str:
    french = _is_french(question)
    if len(df) < 2:
        return f"{_narrate_row(df.iloc[0].to_dict(), french)}."

    first = df.iloc[0].to_dict()
    second = df.iloc[1].to_dict()
    name_a = str(first.get("employee_name", ""))
    name_b = str(second.get("employee_name", ""))
    total_a = float(first.get("total", 0))
    total_b = float(second.get("total", 0))
    amt_a = _format_amount(total_a, french=french)
    amt_b = _format_amount(total_b, french=french)
    if french:
        return f"{name_a} totalise {amt_a}, contre {amt_b} pour {name_b} sur la période."
    return f"{name_a} totals {amt_a}, compared with {amt_b} for {name_b} this period."


def _is_dashboard_help(question: str) -> bool:
    if not _DASHBOARD_HELP_RE.search(question):
        return False
    return not _ANALYTICS_SIGNAL_RE.search(question)


def _is_ambiguous(question: str) -> bool:
    return bool(_AMBIGUOUS_RE.match(question.strip()))


def _mock_dashboard_help(question: str) -> str:
    q = question.lower()
    fr = _is_french(question)
    if re.search(r"approv", q):
        return (
            "Ouvrez Approvals dans le menu de gauche pour voir les demandes en attente "
            "et les approuver ou refuser."
            if fr
            else "Open Approvals in the left sidebar to review pending requests and approve or deny them."
        )
    if re.search(r"flag", q):
        return (
            "Ouvrez Flagged dans le menu de gauche pour consulter les transactions signalées."
            if fr
            else "Open Flagged in the left sidebar to review flagged transactions."
        )
    if re.search(r"import|policy|politique", q):
        return (
            "Ouvrez Policy dans le menu de gauche, puis utilisez Import pour charger un PDF ou du texte."
            if fr
            else "Open Policy in the left sidebar, then use Import to upload a PDF or text."
        )
    return (
        "Utilisez le menu de gauche : Assistant pour les analyses, Approvals, Flagged, "
        "Policy, Transactions et Reports selon votre besoin."
        if fr
        else "Use the left sidebar: Assistant for analytics, Approvals, Flagged, "
        "Policy, Transactions, and Reports as needed."
    )


def _mock_clarification(question: str) -> str:
    if _is_french(question):
        return (
            "Voulez-vous le total en dollars ou le nombre de transactions, et pour quelle période "
            "(ce mois, Q2, 30 derniers jours) ?"
        )
    return (
        "Do you want total spend in dollars or transaction count, and for which period "
        "(this month, Q2, last 30 days)?"
    )


def _scoped_result(
    question: str,
    present: set[str],
    text: str,
    *,
    answered_id: str | None = None,
    sql: str | None = None,
) -> dict:
    return {
        "text": text,
        "followUpSuggestions": suggest_chips(question, present, answered_id),
        "sql": sql,
    }


def _rows_are_marker(rows: list[dict], key: str, value: str) -> bool:
    return bool(rows) and rows[0].get(key) == value


def _match_department(question: str, con) -> str | None:
    q = question.lower()
    for (dept,) in con.execute("SELECT DISTINCT department FROM tx WHERE department IS NOT NULL").fetchall():
        if dept and dept.lower() in q:
            return dept
    return None


def _match_employees(question: str, con) -> list[str]:
    q = question.lower()
    names: list[str] = []
    rows = con.execute(
        "SELECT DISTINCT employee_name FROM tx WHERE employee_name IS NOT NULL ORDER BY employee_name"
    ).fetchall()
    for (name,) in rows:
        if not name:
            continue
        if name.lower() in q:
            names.append(name)
            continue
        for part in name.split():
            if len(part) >= 3 and re.search(rf"\b{re.escape(part.lower())}\b", q):
                if name not in names:
                    names.append(name)
                break
    return names


def _sql_quote(value: str) -> str:
    return value.replace("'", "''")


def _employee_filter_sql(names: list[str]) -> str:
    quoted = ", ".join(f"'{_sql_quote(name)}'" for name in names)
    return f"employee_name IN ({quoted})"


def _is_compare_intent(question: str) -> bool:
    q = question.lower()
    if re.search(r"compare|comparer|versus|\bvs\b|lequel|laquelle", q):
        return True
    if re.search(r"qui\s+(a\s+)?d[ée]pens", q):  # "qui dépense", "qui a dépensé"
        return True
    if re.search(r"\bentre\b.+\bet\b", q):  # "entre X et Y"
        return True
    if re.search(r"plus que|more than|who spent more|who spends more|spends more|spent more", q):
        return True
    return bool(
        re.search(r"\bdeux employ|\btwo employ|\bemployés|\bemployees\b", q)
        and re.search(r"\bet\b|\band\b", q)
    )


def _is_employee_compare_intent(question: str) -> bool:
    q = question.lower()
    return bool(re.search(r"employ|employé|employe", q)) and _is_compare_intent(question)


def _match_category(question: str) -> str | None:
    q = question.lower()
    for cat in BRIM_CATEGORIES:
        if cat.lower() in q:
            return cat
    for pattern, cat in CATEGORY_KEYWORDS:
        if re.search(pattern, q):
            return cat
    return None


_SPEND_LOCATION_INTENT_RE = re.compile(
    r"\b(dépense|dépenses|depense|spend|spent|montre|montrez|liste|list|show|toutes|all)\b",
    re.I,
)
_LOCATION_PREPOSITION_RE = re.compile(
    r"(?:\b(?:à|a|en|in|at|near|pres|près de)\s+)([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s'-]{1,40}?)"
    r"(?:\s*[?.!,]|$|\s+(?:ce|cette|this|last|le|la|les|the|pour|for|du|de|des)\b)",
    re.I,
)


def _extract_location(question: str, con=None) -> str | None:
    """Extract a place name from « dépenses à Illinois », « spend in Chicago », etc."""
    for match in _LOCATION_PREPOSITION_RE.finditer(question):
        place = match.group(1).strip().rstrip("?.!,")
        if len(place) < 2:
            continue
        low = place.lower()
        if low in {"ce", "cette", "this", "the", "les", "des", "du", "de", "la", "le"}:
            continue
        if con is not None:
            for (city,) in con.execute(
                "SELECT DISTINCT city FROM tx WHERE city IS NOT NULL ORDER BY city"
            ).fetchall():
                if city and (city.lower() == low or low in city.lower() or city.lower() in low):
                    return city
        return place
    return None


_US_STATE_LOCATION_SQL: dict[str, str] = {
    "illinois": (
        "(city ILIKE '%Illinois%' OR zipcode ILIKE '%Illinois%' "
        "OR zipcode LIKE '60%' OR zipcode LIKE '61%' OR zipcode LIKE '62%')"
    ),
}


def _location_filter_sql(question: str, con=None) -> str | None:
    place = _extract_location(question, con)
    if not place:
        return None
    state_key = place.lower().strip()
    if state_key in _US_STATE_LOCATION_SQL:
        return _US_STATE_LOCATION_SQL[state_key]
    quoted = _sql_quote(place)
    return f"(city ILIKE '%{quoted}%' OR zipcode ILIKE '%{quoted}%')"


def _is_spend_location_intent(question: str, con=None) -> bool:
    return bool(_SPEND_LOCATION_INTENT_RE.search(question)) and _extract_location(question, con) is not None


def _plan_location_spend(question: str, con) -> dict | None:
    place = _extract_location(question, con)
    if not place or not _SPEND_LOCATION_INTENT_RE.search(question):
        return None
    loc_sql = _location_filter_sql(question, con)
    if not loc_sql:
        return None
    period = _default_period_clause(question)
    clauses = [c for c in (period, loc_sql) if c]
    where = " WHERE " + " AND ".join(clauses) if clauses else f" WHERE {loc_sql}"
    title = f"Dépenses — {place}" if _is_french(question) else f"Spend — {place}"
    return {
        "id": "spend_by_location",
        "chart": "table",
        "title": title,
        "sql": (
            f"SELECT date, employee_name, merchant_name, city, zipcode, amount FROM tx{where} "
            "ORDER BY date DESC"
        ),
    }


def _period_clause(question: str) -> str:
    """A small set of relative periods, computed off the latest transaction date."""
    q = question.lower()
    mx = "(SELECT max(date) FROM tx)"
    if "last quarter" in q:
        return (f"date >= date_trunc('quarter', {mx}) - INTERVAL 3 MONTH "
                f"AND date < date_trunc('quarter', {mx})")
    if "this quarter" in q or "quarter" in q or "trimestre" in q:
        return f"date >= date_trunc('quarter', {mx})"
    if "last month" in q:
        return (f"date >= date_trunc('month', {mx}) - INTERVAL 1 MONTH "
                f"AND date < date_trunc('month', {mx})")
    if "this month" in q or "month" in q or "mois" in q:
        return f"date >= date_trunc('month', {mx})"
    if "this year" in q or "ytd" in q:
        return f"year(date) = year({mx})"
    return ""


def _default_period_clause(question: str) -> str:
    explicit = _period_clause(question)
    if explicit:
        return explicit
    mx = "(SELECT max(date) FROM tx)"
    return f"date >= date_trunc('quarter', {mx})"


def _where_with_period(question: str) -> str:
    period = _default_period_clause(question)
    return f" WHERE {period}" if period else ""


def _plan_employee_compare(question: str, con) -> dict | None:
    employees = _match_employees(question, con)
    compare = _is_compare_intent(question) or _is_employee_compare_intent(question)

    # Two or more named employees is always a comparison, even without "compare".
    if len(employees) < 2 and not compare:
        return None

    period_where = _where_with_period(question)
    q = question.lower()

    if len(employees) >= 2:
        emp_filter = _employee_filter_sql(employees[:2])
        joiner = " AND " if period_where else " WHERE "
        where = f"{period_where}{joiner}{emp_filter}" if period_where else f" WHERE {emp_filter}"
        title = f"Spend comparison — {employees[0]} vs {employees[1]}"
        return {
            "id": "compare_employees",
            "chart": "bar",
            "title": title,
            "sql": (
                f"SELECT employee_name, ROUND(SUM(amount),2) AS total FROM tx{where} "
                "GROUP BY employee_name ORDER BY total DESC"
            ),
        }

    if re.search(r"deux employ|two employ|compare.*employ|employ.*compare", q):
        return {
            "id": "compare_employees",
            "chart": "bar",
            "title": "Top two employees by spend",
            "sql": (
                f"SELECT employee_name, ROUND(SUM(amount),2) AS total FROM tx{period_where} "
                "GROUP BY employee_name ORDER BY total DESC LIMIT 2"
            ),
        }

    if len(employees) == 1:
        dept = None
        for (name, department) in con.execute(
            "SELECT DISTINCT employee_name, department FROM tx WHERE employee_name = ?",
            [employees[0]],
        ).fetchall():
            dept = department
        dept_filter = f"department = '{_sql_quote(dept)}'" if dept else None
        clauses = [c for c in (_default_period_clause(question), dept_filter) if c]
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return {
            "id": "compare_employees",
            "chart": "bar",
            "title": f"Spend comparison near {employees[0]}",
            "sql": (
                f"SELECT employee_name, ROUND(SUM(amount),2) AS total FROM tx{where} "
                "GROUP BY employee_name ORDER BY total DESC LIMIT 2"
            ),
        }

    return None


def mock_plan(question: str, present: set[str], con) -> dict:
    q = question.lower()
    period = _default_period_clause(question)
    where = (" WHERE " + period) if period else ""

    employee_compare = _plan_employee_compare(question, con)
    if employee_compare:
        return employee_compare

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
        clauses = [c for c in (period, f"brim_category = '{cat}'" if cat else "") if c]
        w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return {"id": "compare_depts", "chart": "bar",
                "title": f"Department comparison{(' — ' + cat) if cat else ''}",
                "sql": f"SELECT department, ROUND(SUM(amount),2) AS total FROM tx{w} "
                       f"GROUP BY department ORDER BY total DESC"}

    location_spend = _plan_location_spend(question, con)
    if location_spend:
        return location_spend

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


def _narrate_location_spend(df: pd.DataFrame, question: str, plan: dict) -> str:
    french = _is_french(question)
    title = plan.get("title", "")
    place = title.split("—", 1)[-1].strip() if "—" in title else title.split("-", 1)[-1].strip()
    count = len(df)
    total = float(df["amount"].sum()) if "amount" in df.columns else 0.0
    amt = _format_amount(total, french=french)
    if french:
        return f"{count} dépenses trouvées pour {place}, totalisant {amt}."
    return f"{count} expenses found for {place}, totalling {amt}."


def mock_narrate(question: str, df: pd.DataFrame, plan: dict) -> str:
    french = _is_french(question)
    if df is None or df.empty:
        return _mock_empty_data(question)

    if plan.get("id") == "compare_employees":
        return _narrate_employee_compare(df, question)

    if plan.get("id") == "spend_by_location":
        return _narrate_location_spend(df, question, plan)

    if plan["chart"] == "kpi":
        val = df.iloc[0, 0]
        title = plan.get("title", "")
        if isinstance(val, (int, float)):
            amt = _format_amount(float(val), french=french)
            if french:
                return f"{title} : {amt}."
            return f"{title}: {amt}."
        if french:
            return f"{title} : {val}."
        return f"{title}: {val}."

    top_line = _narrate_row(df.iloc[0].to_dict(), french)
    count = len(df)
    if french:
        if count == 1:
            return f"{top_line}."
        return f"Sur {count} résultats, {top_line}, en tête du classement."
    if count == 1:
        return f"{top_line}."
    return f"Across {count} results, {top_line}, ranking first."


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


# =========================================================================== #
# Visualization: the backend owns column selection and emits a render-ready,
# canonical shape per chart type, so the frontend only renders (no guessing).
#   bar/line -> data.series   = [{name, value}]
#   pie      -> data.segments = [{name, value}]
#   table    -> data.columns + data.rows
#   kpi      -> data.value + data.label
# =========================================================================== #

def _series_keys(df: pd.DataFrame) -> tuple[str, str]:
    """Pick the label column (first non-numeric) and value column (first numeric)."""
    cols = list(df.columns)
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    labels = [c for c in cols if c not in numeric]
    name_key = labels[0] if labels else cols[0]
    value_key = numeric[0] if numeric else cols[-1]
    return name_key, value_key


def _format_kpi_value(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def build_visualization(chart: str, title: str, df: pd.DataFrame | None) -> dict:
    chart = chart if chart in CHART_TYPES else "table"

    if df is None or df.empty:
        empty = {
            "kpi": {"value": "—", "label": title},
            "bar": {"series": []},
            "line": {"series": []},
            "pie": {"segments": []},
            "table": {"columns": [], "rows": []},
        }[chart]
        return {"type": chart, "title": title, "data": empty}

    if chart == "kpi":
        value = df.iloc[0, 0]
        return {"type": "kpi", "title": title,
                "data": {"value": _format_kpi_value(value), "label": title}}

    if chart in ("bar", "line", "pie"):
        name_key, value_key = _series_keys(df)
        points: list[dict] = []
        for _, row in df.iterrows():
            try:
                value = float(row[value_key])
            except (TypeError, ValueError):
                continue
            points.append({"name": str(row[name_key]), "value": value})
        key = "segments" if chart == "pie" else "series"
        return {"type": chart, "title": title, "data": {key: points}}

    # table (default + error fallback)
    columns = [str(c) for c in df.columns]
    rows = [
        ["" if pd.isna(v) else str(v) for v in rec]
        for rec in df.itertuples(index=False, name=None)
    ]
    return {"type": "table", "title": title, "data": {"columns": columns, "rows": rows}}


# =========================================================================== #
# Answer results: a handler per kind of reply. Callers never inspect internal
# state to decide behavior — they call .stream() (SSE events) or .to_dict()
# (JSON). StaticAnswer ships a fixed text; NarratedAnswer streams LLM tokens.
# =========================================================================== #

_COMPUTE_FAIL_LLM = ("I couldn't compute that exactly ({reason}). "
                     "Try one of the suggestions below.")
_COMPUTE_FAIL_MOCK = "I couldn't compute that exactly. Try one of the suggestions below."

_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "loading_data": ("Chargement des données…", "Loading data…"),
    "planning": ("Analyse de la question…", "Analyzing your question…"),
    "running_query": ("Interrogation des dépenses…", "Querying spend data…"),
    "repairing_sql": ("Ajustement de la requête…", "Fixing the query…"),
    "writing": ("Rédaction de la réponse…", "Writing the answer…"),
    "degraded": ("Mode dégradé (réponse locale)…", "Degraded mode (local answer)…"),
}


def _status_event(phase: str, question: str) -> dict:
    fr, en = _STATUS_LABELS.get(phase, (phase, phase))
    message = fr if _is_french(question) else en
    return {"type": "status", "phase": phase, "message": message}


class _AnswerResult:
    def __init__(self, question: str, present: set[str], *, visualization: dict | None = None,
                 sql: str | None = None, error: str | None = None,
                 answered_id: str | None = None, degraded: bool = False):
        self.question = question
        self.visualization = visualization
        self.sql = sql
        self.error = error
        self.degraded = degraded
        self.follow_ups = suggest_chips(question, present, answered_id)
        self._viz_events = (
            [{"type": "visualization", "visualization": visualization}]
            if visualization is not None else []
        )

    @property
    def text(self) -> str:
        raise NotImplementedError

    def _text_events(self):
        raise NotImplementedError

    def stream(self):
        yield from self._viz_events
        yield from self._text_events()
        yield {"type": "follow_up", "suggestions": self.follow_ups}
        yield {"type": "done"}

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "visualization": self.visualization,
            "followUpSuggestions": self.follow_ups,
            "sql": self.sql,
            "_error": self.error,
            "_degraded": self.degraded,
        }


class StaticAnswer(_AnswerResult):
    def __init__(self, text: str, question: str, present: set[str], **kwargs):
        super().__init__(question, present, **kwargs)
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    def _text_events(self):
        yield {"type": "text_delta", "delta": self._text}


class NarratedAnswer(_AnswerResult):
    def __init__(self, stream_factory, full_factory, question: str, present: set[str], **kwargs):
        super().__init__(question, present, **kwargs)
        self._stream_factory = stream_factory
        self._full_factory = full_factory
        self._text_cache: str | None = None

    @property
    def text(self) -> str:
        if self._text_cache is None:
            self._text_cache = self._full_factory()
        return self._text_cache

    def stream(self):
        yield from self._viz_events
        yield _status_event("writing", self.question)
        yield from self._text_events()
        yield {"type": "follow_up", "suggestions": self.follow_ups}
        yield {"type": "done"}

    def _text_events(self):
        chunks: list[str] = []
        for piece in self._stream_factory():
            chunks.append(piece)
            yield {"type": "text_delta", "delta": piece}
        self._text_cache = "".join(chunks)


def _mock_static_answer(con, present: set[str], question: str, on_status) -> _AnswerResult | None:
    if _is_off_topic(question):
        return StaticAnswer(off_topic_refusal(question), question, present)
    if _is_casual_chat(question):
        return StaticAnswer(_mock_greeting(question), question, present)
    if _is_ambiguous(question):
        return StaticAnswer(_mock_clarification(question), question, present)
    if _is_dashboard_help(question):
        return StaticAnswer(_mock_dashboard_help(question), question, present)

    on_status("planning")
    plan = mock_plan(question, present, con)
    on_status("running_query")
    repair_phases: list[str] = []

    def before_repair():
        repair_phases.append("repairing_sql")

    df, sql_used, err = execute_with_repair(con, plan["sql"], None, before_repair=before_repair)
    for phase in repair_phases:
        on_status(phase)
    chart = plan["chart"] if err is None else "table"
    viz = build_visualization(chart, plan["title"], df)
    text = mock_narrate(question, df, plan) if err is None else _COMPUTE_FAIL_MOCK
    return StaticAnswer(text, question, present, visualization=viz,
                        sql=sql_used, error=err, answered_id=plan.get("id"))


def _llm_answer(
    con,
    present: set[str],
    question: str,
    history: str,
    on_status,
) -> _AnswerResult:
    schema = schema_doc(present)
    if _is_casual_chat(question):
        return StaticAnswer(_mock_greeting(question), question, present)

    on_status("planning")
    plan_fn, repair_factory, narrate_fn, narrate_stream_fn = make_llm_steps(schema, history)
    plan = plan_fn(question)
    if not plan.get("in_scope", True):
        return StaticAnswer(off_topic_refusal(question), question, present)

    on_status("running_query")
    repair_phases: list[str] = []

    def before_repair():
        repair_phases.append("repairing_sql")

    df, sql_used, err = execute_with_repair(
        con, plan["sql"], repair_factory(question), before_repair=before_repair,
    )
    for phase in repair_phases:
        on_status(phase)
    rows = _records(df)
    if err is None and _rows_are_marker(rows, "reason", "out_of_scope"):
        return StaticAnswer(off_topic_refusal(question), question, present, sql=sql_used)
    if err is None and _rows_are_marker(rows, "topic", "dashboard_help"):
        return StaticAnswer(narrate_fn(question, rows), question, present, sql=sql_used)
    if err is not None:
        viz = build_visualization("table", plan["title"], df)
        text = _COMPUTE_FAIL_LLM.format(reason=err.splitlines()[0][:120])
        return StaticAnswer(text, question, present, visualization=viz, sql=sql_used, error=err)

    viz = build_visualization(plan["chart"], plan["title"], df)
    return NarratedAnswer(
        lambda: narrate_stream_fn(question, rows),
        lambda: narrate_fn(question, rows),
        question, present, visualization=viz, sql=sql_used,
    )


def _resolve_answer(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
    *,
    on_status=None,
) -> _AnswerResult:
    def status(phase: str) -> None:
        if on_status is not None:
            on_status(phase)

    if not use_llm:
        mock_result = _mock_static_answer(con, present, question, status)
        if mock_result is not None:
            return mock_result
    return _llm_answer(con, present, question, history, status)


def _resolve_answer_stream(con, present: set[str], question: str, history: str, use_llm: bool):
    """Yield status events in real time; return the final _AnswerResult via StopIteration."""
    if not use_llm:
        if _is_off_topic(question):
            return StaticAnswer(off_topic_refusal(question), question, present)
        if _is_casual_chat(question):
            return StaticAnswer(_mock_greeting(question), question, present)
        if _is_ambiguous(question):
            return StaticAnswer(_mock_clarification(question), question, present)
        if _is_dashboard_help(question):
            return StaticAnswer(_mock_dashboard_help(question), question, present)

        yield _status_event("planning", question)
        plan = mock_plan(question, present, con)
        yield _status_event("running_query", question)
        repair_phases: list[str] = []

        def before_repair():
            repair_phases.append("repairing_sql")

        df, sql_used, err = execute_with_repair(con, plan["sql"], None, before_repair=before_repair)
        for phase in repair_phases:
            yield _status_event(phase, question)
        chart = plan["chart"] if err is None else "table"
        viz = build_visualization(chart, plan["title"], df)
        text = mock_narrate(question, df, plan) if err is None else _COMPUTE_FAIL_MOCK
        return StaticAnswer(text, question, present, visualization=viz,
                            sql=sql_used, error=err, answered_id=plan.get("id"))

    if _is_casual_chat(question):
        return StaticAnswer(_mock_greeting(question), question, present)

    schema = schema_doc(present)
    yield _status_event("planning", question)
    plan_fn, repair_factory, narrate_fn, narrate_stream_fn = make_llm_steps(schema, history)
    plan = plan_fn(question)
    if not plan.get("in_scope", True):
        return StaticAnswer(off_topic_refusal(question), question, present)

    yield _status_event("running_query", question)
    repair_phases: list[str] = []

    def before_repair():
        repair_phases.append("repairing_sql")

    df, sql_used, err = execute_with_repair(
        con, plan["sql"], repair_factory(question), before_repair=before_repair,
    )
    for phase in repair_phases:
        yield _status_event(phase, question)
    rows = _records(df)
    if err is None and _rows_are_marker(rows, "reason", "out_of_scope"):
        return StaticAnswer(off_topic_refusal(question), question, present, sql=sql_used)
    if err is None and _rows_are_marker(rows, "topic", "dashboard_help"):
        return StaticAnswer(narrate_fn(question, rows), question, present, sql=sql_used)
    if err is not None:
        viz = build_visualization("table", plan["title"], df)
        text = _COMPUTE_FAIL_LLM.format(reason=err.splitlines()[0][:120])
        return StaticAnswer(text, question, present, visualization=viz, sql=sql_used, error=err)

    viz = build_visualization(plan["chart"], plan["title"], df)
    return NarratedAnswer(
        lambda: narrate_stream_fn(question, rows),
        lambda: narrate_fn(question, rows),
        question, present, visualization=viz, sql=sql_used,
    )


def prepare_answer(con, present: set[str], question: str, history: str, use_llm: bool) -> _AnswerResult:
    return _resolve_answer(con, present, question, history, use_llm)


def stream_answer_events(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
    *,
    degraded: bool = False,
):
    """SSE generator: status events during prep, then result.stream()."""
    if degraded:
        yield _status_event("degraded", question)

    gen = _resolve_answer_stream(con, present, question, history, use_llm)
    result = None
    while True:
        try:
            yield next(gen)
        except StopIteration as stop:
            result = stop.value
            break
    if result is not None:
        yield from result.stream()


def answer(con, present: set[str], question: str, history: str, use_llm: bool) -> dict:
    return prepare_answer(con, present, question, history, use_llm).to_dict()


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
    ap.add_argument("--model", default=None, help="Gemini model id (default gemini-3.1-flash-lite).")
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
        mode = (os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite") if use_llm else "mock")
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
