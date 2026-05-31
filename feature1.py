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
    {"id": "spend_by_department", "chip": "Spend by department", "needs": ["tx"],
     "kw": r"department|dept|département"},
    {"id": "spend_by_category", "chip": "Spend by category", "needs": ["tx"],
     "kw": r"category|brim_category|mcc"},
    {"id": "spend_by_city", "chip": "Spend by city", "needs": ["tx"],
     "kw": r"city|ville|location|cities"},
    {"id": "total_spend", "chip": "Total company spend", "needs": ["tx"],
     "kw": r"total spend|company spend|overall"},
    {"id": "top_employees", "chip": "Top employee spenders", "needs": ["tx"],
     "kw": r"top|spender|employee.*spend|employé|employe"},
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


_SPEND_CAP_IDS = frozenset({
    "spend_by_dept_cat",
    "spend_by_department",
    "spend_by_category",
    "spend_by_city",
    "total_spend",
    "top_employees",
    "compare_depts",
    "compare_employees",
    "top_merchants",
    "spend_trend",
})
_COMPLIANCE_CAP_IDS = frozenset({"most_flagged", "repeat_offenders", "split_attempts"})
_BUDGET_CAP_IDS = frozenset({"budget_status"})

_VIZ_CHIP_BIAS: dict[str, str] = {
    "bar": "spend_by_dept_cat",
    "line": "spend_trend",
    "table": "top_employees",
    "pie": "spend_by_category",
    "kpi": "total_spend",
}


def _cap_family(cap_id: str) -> str | None:
    if cap_id in _SPEND_CAP_IDS:
        return "spend"
    if cap_id in _COMPLIANCE_CAP_IDS:
        return "compliance"
    if cap_id in _BUDGET_CAP_IDS:
        return "budget"
    return None


def suggest_chips(
    question: str,
    present: set[str],
    answered_id: str | None,
    *,
    viz_type: str | None = None,
) -> list[str]:
    """Rank capabilities by relevance, pivot away from the answered family, and bias by viz shape."""
    q = question.lower()
    caps = [c for c in available_capabilities(present) if c["id"] != answered_id]
    answered_family = _cap_family(answered_id) if answered_id else None
    pivot_families: set[str] = set()
    if answered_family == "spend":
        pivot_families = {"compliance", "budget"}
    elif answered_family == "compliance":
        pivot_families = {"spend", "budget"}
    elif answered_family == "budget":
        pivot_families = {"spend", "compliance"}

    viz_bias_id = _VIZ_CHIP_BIAS.get(viz_type or "")

    def score(cap: dict) -> tuple:
        cap_id = cap["id"]
        kw_hit = bool(re.search(cap["kw"], q))
        family = _cap_family(cap_id)
        pivot = 1 if family and family in pivot_families else 0
        viz_match = 1 if viz_bias_id and cap_id == viz_bias_id else 0
        return (pivot, kw_hit, viz_match, cap_id)

    scored = sorted(caps, key=score, reverse=True)
    chips = [c["chip"] for c in scored[:3]]
    if chips:
        return chips
    return [c["chip"] for c in available_capabilities(present)[:3]]


# =========================================================================== #
# Contextual follow-ups (LLM + heuristics; registry chips as last resort)
# =========================================================================== #

_FOLLOW_UP_ENTITY_KEYS = (
    "employee_name",
    "department",
    "city",
    "merchant_name",
    "brim_category",
)


def _collect_column_values(rows: list[dict], key: str, limit: int = 5) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        raw = row.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _viz_series_names(viz: dict | None, limit: int = 5) -> list[str]:
    if not viz:
        return []
    data = viz.get("data") or {}
    names: list[str] = []
    for bucket in ("series", "segments"):
        for item in data.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
            if len(names) >= limit:
                return names
    return names


def _follow_up_context(
    question: str,
    present: set[str],
    rows: list[dict] | None,
    *,
    plan: dict | None = None,
    viz: dict | None = None,
    answered_id: str | None = None,
) -> dict:
    rows = rows or []
    viz = viz or {}
    employees = _collect_column_values(rows, "employee_name")
    departments = _collect_column_values(rows, "department")
    cities = _collect_column_values(rows, "city")
    merchants = _collect_column_values(rows, "merchant_name")
    categories = _collect_column_values(rows, "brim_category")

    series_names = _viz_series_names(viz)
    if not employees and series_names and answered_id in ("top_employees", None):
        if plan and plan.get("chart") in ("bar", "pie", "table"):
            employees = series_names[:5]
    if not departments and series_names and answered_id in (
        "spend_by_department",
        "spend_by_dept_cat",
        None,
    ):
        departments = series_names[:5]

    caps = available_capabilities(present)
    return {
        "present": present,
        "question": question,
        "french": _is_french(question),
        "answered_id": answered_id,
        "plan_title": (plan or {}).get("title"),
        "plan_chart": (plan or {}).get("chart"),
        "viz_type": viz.get("type"),
        "viz_title": viz.get("title"),
        "rows_sample": rows[:8],
        "employees": employees,
        "departments": departments,
        "cities": cities,
        "merchants": merchants,
        "categories": categories,
        "series_names": series_names,
        "capabilities": [{"id": c["id"], "chip": c["chip"]} for c in caps],
        "has_flags": "flags" in present,
        "has_strikes": "strikes" in present,
        "has_budget": "budget" in present,
    }


def _follow_up_item(
    label: str,
    prompt: str,
    hint: str,
    *,
    angle: str = "pivot",
) -> dict:
    return {
        "label": label[:48],
        "prompt": prompt.strip(),
        "hint": hint.strip(),
        "angle": angle,
    }


def _chips_to_structured(chips: list[str], ctx: dict) -> list[dict]:
    fr = ctx.get("french", False)
    out: list[dict] = []
    for chip in chips[:3]:
        out.append(
            _follow_up_item(
                chip,
                chip,
                (
                    "Suite suggérée à votre dernière question."
                    if fr
                    else "Suggested next step from your last question."
                ),
            )
        )
    return out


def suggest_contextual_follow_ups(ctx: dict) -> list[dict]:
    """Rule-based contextual follow-ups for mock / degraded paths."""
    fr = bool(ctx.get("french"))
    q = ctx.get("question") or ""
    aid = ctx.get("answered_id")
    employees: list[str] = list(ctx.get("employees") or [])
    departments: list[str] = list(ctx.get("departments") or [])
    merchants: list[str] = list(ctx.get("merchants") or [])
    categories: list[str] = list(ctx.get("categories") or [])
    cities: list[str] = list(ctx.get("cities") or [])
    has_flags = bool(ctx.get("has_flags"))
    has_budget = bool(ctx.get("has_budget"))

    emp = employees[0] if employees else None
    dept = departments[0] if departments else None
    dept2 = departments[1] if len(departments) > 1 else None
    merchant = merchants[0] if merchants else None
    category = categories[0] if categories else None
    city = cities[0] if cities else None

    period_fr = ""
    period_en = ""
    if _period_clause(q):
        period_fr = " pour la même période"
        period_en = " for the same period"

    items: list[dict] = []

    if aid == "top_employees" and emp:
        if fr:
            items.append(
                _follow_up_item(
                    f"{emp.split()[0]} — par catégorie",
                    f"Détail des dépenses de {emp} par catégorie{period_fr}",
                    f"Zoom sur le premier employé du classement ({emp}).",
                    angle="narrow",
                )
            )
            pivot_dept = dept or "son département"
            items.append(
                _follow_up_item(
                    "Dépenses par département",
                    f"Montre les dépenses par département{period_fr}",
                    f"Compare les départements, dont celui de {emp}.",
                    angle="pivot",
                )
            )
            if has_flags:
                items.append(
                    _follow_up_item(
                        "Flags de conformité",
                        f"Quels flags de conformité pour {emp} ?",
                        "Élargir vers la conformité pour cet employé.",
                        angle="broaden",
                    )
                )
            else:
                items.append(
                    _follow_up_item(
                        "Tendance mensuelle",
                        "Montre la tendance mensuelle des dépenses cette année",
                        "Vue plus large dans le temps.",
                        angle="broaden",
                    )
                )
        else:
            items.append(
                _follow_up_item(
                    f"{emp.split()[0]} — by category",
                    f"Show {emp}'s spend breakdown by category{period_en}",
                    f"Drill into the top spender ({emp}).",
                    angle="narrow",
                )
            )
            items.append(
                _follow_up_item(
                    "Spend by department",
                    f"Show spend by department{period_en}",
                    "Pivot to department totals.",
                    angle="pivot",
                )
            )
            if has_flags:
                items.append(
                    _follow_up_item(
                        "Compliance flags",
                        f"Which compliance flags does {emp} have?",
                        "Broaden to compliance for this employee.",
                        angle="broaden",
                    )
                )
            else:
                items.append(
                    _follow_up_item(
                        "Monthly spend trend",
                        "Show monthly company spend trend this year",
                        "Broader time-series view.",
                        angle="broaden",
                    )
                )

    elif aid in ("spend_by_department", "spend_by_dept_cat") and dept:
        if fr:
            items.append(
                _follow_up_item(
                    f"Top employés — {dept}",
                    f"Top 10 employés les plus dépensiers dans {dept}{period_fr}",
                    f"Zoom sur le département leader ({dept}).",
                    angle="narrow",
                )
            )
            if dept2:
                items.append(
                    _follow_up_item(
                        f"Comparer {dept} et {dept2}",
                        f"Compare les dépenses entre {dept} et {dept2}{period_fr}",
                        "Comparer deux départements du résultat.",
                        angle="pivot",
                    )
                )
            else:
                items.append(
                    _follow_up_item(
                        "Par catégorie",
                        f"Montre les dépenses par catégorie{period_fr}",
                        "Autre dimension de dépense.",
                        angle="pivot",
                    )
                )
            if has_budget:
                items.append(
                    _follow_up_item(
                        "Dépassements budget",
                        f"Quels départements dépassent le budget ce trimestre ?",
                        "Relier dépenses et budgets.",
                        angle="broaden",
                    )
                )
            elif has_flags:
                items.append(
                    _follow_up_item(
                        "Employés les plus flaggés",
                        "Quels employés ont le plus de flags de conformité ?",
                        "Passer à la conformité.",
                        angle="broaden",
                    )
                )
            else:
                items.append(
                    _follow_up_item(
                        "Top employés (entreprise)",
                        "Top 10 employés les plus dépensiers",
                        "Vue entreprise plus large.",
                        angle="broaden",
                    )
                )
        else:
            items.append(
                _follow_up_item(
                    f"Top spenders — {dept}",
                    f"Top 10 employee spenders in {dept}{period_en}",
                    f"Drill into leading department ({dept}).",
                    angle="narrow",
                )
            )
            if dept2:
                items.append(
                    _follow_up_item(
                        f"Compare {dept} vs {dept2}",
                        f"Compare spend between {dept} and {dept2}{period_en}",
                        "Compare two departments from the chart.",
                        angle="pivot",
                    )
                )
            else:
                items.append(
                    _follow_up_item(
                        "Spend by category",
                        f"Show spend by category{period_en}",
                        "Pivot to expense categories.",
                        angle="pivot",
                    )
                )
            if has_budget:
                items.append(
                    _follow_up_item(
                        "Over budget",
                        "Which departments are over budget this quarter?",
                        "Connect spend to budgets.",
                        angle="broaden",
                    )
                )
            elif has_flags:
                items.append(
                    _follow_up_item(
                        "Most flagged employees",
                        "Which employees have the most compliance flags?",
                        "Broaden to compliance.",
                        angle="broaden",
                    )
                )
            else:
                items.append(
                    _follow_up_item(
                        "Top company spenders",
                        "Top 10 employee spenders",
                        "Company-wide ranking.",
                        angle="broaden",
                    )
                )

    elif aid == "spend_by_category" and category:
        narrow_l = f"{category[:20]} — par employé" if fr else f"{category[:20]} — by employee"
        if fr:
            items.extend(
                [
                    _follow_up_item(
                        narrow_l,
                        f"Top employés pour la catégorie {category}{period_fr}",
                        f"Qui dépense le plus en {category} ?",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Par département",
                        f"Dépenses par département{period_fr}",
                        "Changer de dimension.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Top commerçants",
                        f"Top commerçants pour {category}{period_fr}",
                        "Voir les fournisseurs dominants.",
                        angle="broaden",
                    ),
                ]
            )
        else:
            items.extend(
                [
                    _follow_up_item(
                        narrow_l,
                        f"Top employees for {category}{period_en}",
                        f"Who spends most on {category}?",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Spend by department",
                        f"Show spend by department{period_en}",
                        "Pivot to departments.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Top merchants",
                        f"Top merchants for {category}{period_en}",
                        "See dominant vendors.",
                        angle="broaden",
                    ),
                ]
            )

    elif aid == "spend_by_city" and city:
        if fr:
            items.extend(
                [
                    _follow_up_item(
                        f"Dépenses — {city}",
                        f"Liste les transactions à {city}{period_fr}",
                        f"Détail des dépenses à {city}.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Par employé",
                        f"Top employés avec dépenses à {city}{period_fr}",
                        "Qui dépense dans cette ville ?",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Toutes les villes",
                        "Montre les dépenses par ville",
                        "Revenir à une vue globale des villes.",
                        angle="broaden",
                    ),
                ]
            )
        else:
            items.extend(
                [
                    _follow_up_item(
                        f"Transactions — {city}",
                        f"List recent transactions in {city}{period_en}",
                        f"Transaction detail in {city}.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Top spenders",
                        f"Top employees spending in {city}{period_en}",
                        "Who spends in this city?",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "All cities",
                        "Show spend by city",
                        "Back to all cities.",
                        angle="broaden",
                    ),
                ]
            )

    elif aid == "top_merchants" and merchant:
        if fr:
            items.extend(
                [
                    _follow_up_item(
                        f"Transactions — {merchant[:24]}",
                        f"Liste les transactions chez {merchant}{period_fr}",
                        "Détail chez ce commerçant.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Par département",
                        f"Dépenses par département chez {merchant}{period_fr}",
                        "Répartition interne.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Top commerçants",
                        "Top commerçants par dépenses",
                        "Classement global.",
                        angle="broaden",
                    ),
                ]
            )
        else:
            items.extend(
                [
                    _follow_up_item(
                        f"At {merchant[:24]}",
                        f"List transactions at {merchant}{period_en}",
                        "Drill into this merchant.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "By department",
                        f"Spend by department at {merchant}{period_en}",
                        "Internal split.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Top merchants",
                        "Show top merchants by spend",
                        "Company-wide merchant ranking.",
                        angle="broaden",
                    ),
                ]
            )

    elif aid in ("most_flagged", "repeat_offenders", "split_attempts") and emp:
        if fr:
            items.extend(
                [
                    _follow_up_item(
                        f"Dépenses — {emp.split()[0]}",
                        f"Montre les dépenses de {emp}{period_fr}",
                        "Contexte financier de l'employé flaggé.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Par catégorie",
                        f"Dépenses par catégorie{period_fr}",
                        "Revenir aux dépenses par type.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Tentatives de split",
                        "Montre les tentatives d'achat fractionné ce trimestre",
                        "Autre angle conformité.",
                        angle="broaden",
                    ),
                ]
            )
        else:
            items.extend(
                [
                    _follow_up_item(
                        f"Spend — {emp.split()[0]}",
                        f"Show {emp}'s spend{period_en}",
                        "Financial context for flagged employee.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Spend by category",
                        f"Show spend by category{period_en}",
                        "Pivot back to spend types.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Split attempts",
                        "Show split-purchase attempts this quarter",
                        "Another compliance angle.",
                        angle="broaden",
                    ),
                ]
            )

    elif aid == "budget_status" and dept:
        if fr:
            items.extend(
                [
                    _follow_up_item(
                        f"Dépenses — {dept}",
                        f"Dépenses du département {dept} ce trimestre",
                        "Détail du département en dépassement.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Comparer départements",
                        f"Compare les dépenses entre {dept} et un autre département",
                        "Comparer budgets et dépenses.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Top employés",
                        "Top 10 employés les plus dépensiers",
                        "Vue dépenses globale.",
                        angle="broaden",
                    ),
                ]
            )
        else:
            items.extend(
                [
                    _follow_up_item(
                        f"Spend — {dept}",
                        f"Show {dept} department spend this quarter",
                        "Drill into over-budget department.",
                        angle="narrow",
                    ),
                    _follow_up_item(
                        "Compare departments",
                        f"Compare spend between {dept} and another department",
                        "Budget vs spend comparison.",
                        angle="pivot",
                    ),
                    _follow_up_item(
                        "Top spenders",
                        "Top 10 employee spenders",
                        "Company-wide spend view.",
                        angle="broaden",
                    ),
                ]
            )

    if len(items) >= 3:
        return items[:3]

    # Generic contextual fallbacks when we have entities but no template matched
    if emp and len(items) < 3:
        if fr:
            items.append(
                _follow_up_item(
                    f"{emp.split()[0]} — détail",
                    f"Détail des dépenses de {emp}{period_fr}",
                    "Zoom employé.",
                    angle="narrow",
                )
            )
        else:
            items.append(
                _follow_up_item(
                    f"{emp.split()[0]} — detail",
                    f"Show {emp}'s spend breakdown{period_en}",
                    "Employee drill-down.",
                    angle="narrow",
                )
            )
    if dept and len(items) < 3:
        if fr:
            items.append(
                _follow_up_item(
                    f"Dépenses — {dept}",
                    f"Top employés dans {dept}{period_fr}",
                    "Zoom département.",
                    angle="pivot",
                )
            )
        else:
            items.append(
                _follow_up_item(
                    f"Spend — {dept}",
                    f"Top spenders in {dept}{period_en}",
                    "Department drill-down.",
                    angle="pivot",
                )
            )

    if len(items) < 3:
        present = ctx.get("present") or {"tx"}
        viz_type = ctx.get("viz_type")
        chips = suggest_chips(q, present, aid, viz_type=viz_type)
        for structured in _chips_to_structured(chips, ctx):
            if len(items) >= 3:
                break
            prompts = {i["prompt"] for i in items}
            if structured["prompt"] not in prompts:
                items.append(structured)

    present = ctx.get("present") or {"tx"}
    return items[:3] if items else _chips_to_structured(
        suggest_chips(q, present, aid, viz_type=ctx.get("viz_type")),
        ctx,
    )


def _follow_up_schema():
    from pydantic import BaseModel, Field

    class FollowUpItem(BaseModel):
        label: str = Field(description="Short chip label, max ~48 characters")
        prompt: str = Field(description="Full follow-up question sent to the assistant")
        hint: str = Field(description="One-line tooltip explaining why this is useful")
        angle: str = Field(description="narrow | pivot | broaden")

    class FollowUpSet(BaseModel):
        items: list[FollowUpItem] = Field(
            description="Exactly three diverse follow-up suggestions"
        )

    return FollowUpSet


FOLLOW_UP_SYSTEM = """You suggest exactly three follow-up questions for a finance analytics
chat. The user just asked a question and received an answer with SQL result rows.

Rules:
- Return exactly 3 items with angles: one "narrow" (drill into a specific employee,
  department, merchant, or city from the context), one "pivot" (different dimension:
  category, department, city, merchants, employees), one "broaden" (wider lens: company-wide
  ranking, monthly trend, compliance flags, budget status, or all-time) when relevant.
- Use real entity names from the context (employees, departments, etc.) — never invent names.
- Each prompt must be answerable using only the available capability areas listed in context.
- Do NOT repeat the user's last question verbatim.
- Match the user's language (French questions → French labels and prompts).
- Labels are short (under 48 chars); prompts are complete questions.
- If compliance (flags/strikes) or budget data is available, include at least one non-spend
  angle when it fits the broaden slot.

Context JSON:
{context_json}"""


def _generate_follow_ups_llm_inner(ctx: dict) -> list[dict]:
    from langchain_core.prompts import ChatPromptTemplate

    chain = (
        ChatPromptTemplate.from_messages(
            [("system", FOLLOW_UP_SYSTEM), ("human", "Suggest three follow-ups.")]
        ).partial(context_json=json.dumps(ctx, ensure_ascii=False, default=str))
        | make_chat_llm().with_structured_output(_follow_up_schema())
    )
    result = chain.invoke({})
    items = getattr(result, "items", None) or result.get("items", [])
    out: list[dict] = []
    for item in items[:3]:
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            continue
        label = str(data.get("label") or "").strip()
        prompt = str(data.get("prompt") or "").strip()
        hint = str(data.get("hint") or "").strip()
        if not label or not prompt:
            continue
        out.append(
            _follow_up_item(
                label,
                prompt,
                hint or prompt,
                angle=str(data.get("angle") or "pivot"),
            )
        )
    return out if len(out) == 3 else []


def generate_follow_ups_llm(ctx: dict) -> list[dict] | None:
    import concurrent.futures

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_generate_follow_ups_llm_inner, ctx)
            return future.result(timeout=3.0)
    except Exception:
        return None


def resolve_follow_ups(
    question: str,
    present: set[str],
    answered_id: str | None,
    rows: list[dict] | None,
    *,
    plan: dict | None = None,
    viz: dict | None = None,
    use_llm_for_followups: bool = False,
) -> list[dict]:
    """Structured follow-ups: LLM when enabled, else heuristics, else registry chips."""
    ctx = _follow_up_context(
        question,
        present,
        rows,
        plan=plan,
        viz=viz,
        answered_id=answered_id,
    )
    if not rows and not ctx.get("series_names"):
        return _chips_to_structured(
            suggest_chips(
                question,
                present,
                answered_id,
                viz_type=ctx.get("viz_type"),
            ),
            ctx,
        )

    if use_llm_for_followups:
        llm_items = generate_follow_ups_llm(ctx)
        if llm_items and len(llm_items) == 3:
            return llm_items

    contextual = suggest_contextual_follow_ups(ctx)
    if len(contextual) >= 3:
        return contextual[:3]

    chips = suggest_chips(
        question,
        present,
        answered_id,
        viz_type=ctx.get("viz_type"),
    )
    merged = contextual + _chips_to_structured(chips, ctx)
    seen: set[str] = set()
    out: list[dict] = []
    for item in merged:
        key = item["prompt"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) == 3:
            break
    return out


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


_ALL_TIME_INTENT_RE = re.compile(
    r"\b("
    r"all[- ]?time|entire history|full history|since the beginning|"
    r"toute la période|historique complet|depuis le début|ever"
    r")\b",
    re.I,
)


def _is_all_time_intent(question: str) -> bool:
    return bool(_ALL_TIME_INTENT_RE.search(question))


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


# Aggregate over `date` used bare inside a WHERE/HAVING clause — DuckDB rejects this
# ("aggregates are not allowed in WHERE"). The LLM occasionally emits it for "current quarter".
_AGG_OVER_DATE = re.compile(r"\b(max|min|avg|sum|count)\s*\(\s*(?:tx\.)?date\s*\)", re.I)


def _fix_aggregate_in_where(sql: str) -> str | None:
    """Rewrite a bare aggregate over `date` inside WHERE/HAVING into a scalar subquery.

    Returns the corrected SQL, or None when the pattern is absent. Scoped to the WHERE/HAVING
    span so legitimate aggregates in the SELECT list / GROUP BY / ORDER BY are untouched.
    """
    where = re.search(r"\b(where|having)\b", sql, re.I)
    if not where:
        return None
    start = where.end()
    tail = re.search(r"\b(group\s+by|order\s+by|limit|window|qualify)\b", sql[start:], re.I)
    end = start + tail.start() if tail else len(sql)
    clause = sql[start:end]
    if not _AGG_OVER_DATE.search(clause):
        return None

    def _wrap(m: re.Match) -> str:
        # Skip an aggregate already projected by a subquery (…(SELECT max(date) FROM tx)…)
        # to avoid double-wrapping it into a non-scalar subquery.
        if re.search(r"select\s+$", clause[: m.start()], re.I):
            return m.group(0)
        return f"(SELECT {m.group(1).lower()}(date) FROM tx)"

    fixed = _AGG_OVER_DATE.sub(_wrap, clause)
    if fixed == clause:
        return None
    return sql[:start] + fixed + sql[end:]


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
            if attempt == REPAIR_RETRIES:
                break
            # 1) Cheap deterministic fix for the common aggregate-in-WHERE error — try it
            #    first so a correct rewrite doesn't burn an LLM repair round.
            det = _fix_aggregate_in_where(sql)
            if det is not None and det != sql:
                sql = det
                if before_repair is not None:
                    before_repair()
                continue
            # 2) Otherwise fall back to the LLM repair.
            if repair is None:
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

CRITICAL: WHERE and HAVING must never contain a bare aggregate. To reference the latest
date, use a scalar subquery — date_trunc('quarter', (SELECT max(date) FROM tx)) — never
date_trunc('quarter', max(date)), which DuckDB rejects (aggregates are not allowed in WHERE).

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

Period defaults: table tx is the full loaded dataset — there is no session toolbar filter.
Add date predicates only when the user names a period in their question (e.g. this quarter,
last month, all time). Do NOT assume the current quarter when no period is mentioned. For
counts or lookups of flagged transactions, compliance flags, strikes, or approvals — and for
"which one / laquelle" follow-ups — do NOT add any date filter unless the user names a period.
Use ROUND(SUM(amount),2) for spend comparisons. Filter tx.employee_name when two employees
are named or when comparing employees.

Rankings and breakdowns: for "top N employees/spenders" use GROUP BY employee_name,
ORDER BY ROUND(SUM(amount),2) DESC, LIMIT N (default 10). For top departments use GROUP BY
department; for categories use brim_category; for cities use city. Use chart=bar or table for
ranked lists. Do not return a single-row KPI when the user asked for a top/ranked list.

{schema}

Conversation so far (for follow-ups; resolve pronouns/comparisons against it):
{history}"""

NARRATE_BASE = """You are a finance analytics assistant. Given the question and the query
result rows (JSON), write a concise 1-3 sentence answer for a non-technical finance manager.
Reference the actual numbers. Do not invent data beyond the rows. No preamble.
Report only what the rows contain: if the question asks for N items (e.g. "top 3") but fewer
rows are returned, describe exactly the rows present and never state a higher count than the
rows support. Match any count you mention to the number of rows. For ranked employee lists,
name every employee row returned (up to the limit), not only the first."""


def make_llm_steps(schema: str, history: str):
    from langchain_core.prompts import ChatPromptTemplate

    narrate_system = build_narrate_system(NARRATE_BASE)

    plan_chain = ChatPromptTemplate.from_messages(
        [("system", PLAN_SYSTEM), ("human", "{question}")]
    ).partial(
        schema=schema,
        history=history or "(none)",
    ) | make_chat_llm().with_structured_output(_plan_schema())

    repair_chain = ChatPromptTemplate.from_messages([
        ("system", "Fix this DuckDB SQL. Return ONLY the corrected single SELECT.\n\n" + schema),
        ("human", "Question: {question}\nSQL:\n{sql}\nError: {error}"),
    ]) | make_chat_llm()

    narrate_chain = ChatPromptTemplate.from_messages(
        [("system", narrate_system), ("human", "Question: {question}\nRows: {rows}")]
    ) | make_chat_llm()

    def plan(question: str) -> dict:
        p = plan_chain.invoke({"question": question})
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
        "followUpSuggestions": resolve_follow_ups(
            question, present, answered_id, None
        ),
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
    if _is_all_time_intent(question):
        return ""
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
    return _period_clause(question)


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


def _parse_top_n(question: str, default: int = 10) -> int:
    match = re.search(r"\btop\s*(\d+)\b", question, re.I)
    if match:
        return max(1, min(50, int(match.group(1))))
    return default


def _is_top_employees_intent(question: str) -> bool:
    q = question.lower()
    if re.search(r"\btop\s*\d*\s*(employee|employé|employe|spender)", q):
        return True
    if re.search(r"(employee|employé|employe).*(top|spender|spend)", q):
        return True
    if re.search(r"\bspender", q) and ("employee" in q or "employ" in q):
        return True
    return False


def mock_plan(question: str, present: set[str], con) -> dict:
    q = question.lower()
    period = _default_period_clause(question)
    where = (" WHERE " + period) if period else ""

    employee_compare = _plan_employee_compare(question, con)
    if employee_compare:
        return employee_compare

    if _is_top_employees_intent(question):
        n = _parse_top_n(question, 10)
        period_clause = period
        clauses = [c for c in (period_clause, "employee_name IS NOT NULL") if c]
        w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return {
            "id": "top_employees",
            "chart": "bar",
            "title": f"Top {n} employee spenders",
            "sql": (
                f"SELECT employee_name, ROUND(SUM(amount),2) AS total FROM tx{w} "
                f"GROUP BY employee_name ORDER BY total DESC LIMIT {n}"
            ),
        }

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

    if re.search(r"total\s+(company\s+)?spend|overall\s+spend|company\s+spend", q) and not re.search(
        r"\bby\b|\bper\b|department|employee|city|ville", q
    ):
        clauses = [c for c in (period,) if c]
        w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return {
            "id": "total_spend",
            "chart": "kpi",
            "title": "Total company spend",
            "sql": f"SELECT ROUND(SUM(amount),2) AS total FROM tx{w}",
        }

    if re.search(r"\b(city|cities|ville)\b", q) and re.search(
        r"spend|spent|top|breakdown|by", q
    ) and not _is_spend_location_intent(question, con):
        n = _parse_top_n(question, 10)
        clauses = [c for c in (period, "city IS NOT NULL") if c]
        w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return {
            "id": "spend_by_city",
            "chart": "bar",
            "title": f"Top {n} cities by spend",
            "sql": (
                f"SELECT city, ROUND(SUM(amount),2) AS total FROM tx{w} "
                f"GROUP BY city ORDER BY total DESC LIMIT {n}"
            ),
        }

    if re.search(r"category|brim_category|mcc", q) and re.search(r"spend|spent|breakdown|by", q):
        clauses = [c for c in (period,) if c]
        w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return {
            "id": "spend_by_category",
            "chart": "bar",
            "title": "Spend by category",
            "sql": (
                f"SELECT brim_category, ROUND(SUM(amount),2) AS total FROM tx{w} "
                f"GROUP BY brim_category ORDER BY total DESC"
            ),
        }

    if re.search(r"department|dept|département", q) and re.search(
        r"spend|spent|breakdown|by", q
    ) and not re.search(r"compare|versus|\bvs\b", q):
        clauses = [c for c in (period,) if c]
        w = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return {
            "id": "spend_by_department",
            "chart": "bar",
            "title": "Spend by department",
            "sql": (
                f"SELECT department, ROUND(SUM(amount),2) AS total FROM tx{w} "
                f"GROUP BY department ORDER BY total DESC"
            ),
        }

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
    def __init__(
        self,
        question: str,
        present: set[str],
        *,
        visualization: dict | None = None,
        sql: str | None = None,
        error: str | None = None,
        answered_id: str | None = None,
        degraded: bool = False,
        rows: list[dict] | None = None,
        plan: dict | None = None,
        use_llm_for_followups: bool = False,
        skip_follow_ups: bool = False,
    ):
        self.question = question
        self.present = present
        self.visualization = visualization
        self.sql = sql
        self.error = error
        self.degraded = degraded
        self.answered_id = answered_id
        self.rows = rows or []
        self.plan = plan
        self.use_llm_for_followups = use_llm_for_followups
        self.skip_follow_ups = skip_follow_ups
        self._follow_ups_cache: list[dict] | None = None
        self._viz_events = (
            [{"type": "visualization", "visualization": visualization}]
            if visualization is not None else []
        )

    def _resolve_follow_ups(self) -> list[dict]:
        if self._follow_ups_cache is not None:
            return self._follow_ups_cache
        if self.skip_follow_ups:
            self._follow_ups_cache = []
            return self._follow_ups_cache
        self._follow_ups_cache = resolve_follow_ups(
            self.question,
            self.present,
            self.answered_id,
            self.rows,
            plan=self.plan,
            viz=self.visualization,
            use_llm_for_followups=self.use_llm_for_followups,
        )
        return self._follow_ups_cache

    @property
    def follow_ups(self) -> list[dict]:
        return self._resolve_follow_ups()

    @property
    def text(self) -> str:
        raise NotImplementedError

    def _text_events(self):
        raise NotImplementedError

    def stream(self):
        yield from self._viz_events
        yield from self._text_events()
        follow_ups = self._resolve_follow_ups()
        if follow_ups:
            yield {"type": "follow_up", "suggestions": follow_ups}
        yield {"type": "done"}

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "visualization": self.visualization,
            "followUpSuggestions": self._resolve_follow_ups(),
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
        return StaticAnswer(
            off_topic_refusal(question), question, present, skip_follow_ups=True
        )
    if _is_casual_chat(question):
        return StaticAnswer(
            _mock_greeting(question), question, present, skip_follow_ups=True
        )
    if _is_ambiguous(question):
        return StaticAnswer(
            _mock_clarification(question), question, present, skip_follow_ups=True
        )
    if _is_dashboard_help(question):
        return StaticAnswer(
            _mock_dashboard_help(question), question, present, skip_follow_ups=True
        )

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
    rows = _records(df) if err is None else []
    return StaticAnswer(
        text,
        question,
        present,
        visualization=viz,
        sql=sql_used,
        error=err,
        answered_id=plan.get("id"),
        rows=rows,
        plan=plan,
        use_llm_for_followups=False,
    )


def _llm_answer(
    con,
    present: set[str],
    question: str,
    history: str,
    on_status,
    *,
    use_llm_for_followups: bool = True,
) -> _AnswerResult:
    schema = schema_doc(present)
    if _is_casual_chat(question):
        return StaticAnswer(
            _mock_greeting(question), question, present, skip_follow_ups=True
        )

    on_status("planning")
    plan_fn, repair_factory, narrate_fn, narrate_stream_fn = make_llm_steps(
        schema, history
    )
    plan = plan_fn(question)
    if not plan.get("in_scope", True):
        return StaticAnswer(
            off_topic_refusal(question), question, present, skip_follow_ups=True
        )

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
        question,
        present,
        visualization=viz,
        sql=sql_used,
        rows=rows,
        plan=plan,
        use_llm_for_followups=use_llm_for_followups,
    )


def _resolve_answer(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
    *,
    on_status=None,
    use_llm_for_followups: bool | None = None,
) -> _AnswerResult:
    def status(phase: str) -> None:
        if on_status is not None:
            on_status(phase)

    followups_llm = use_llm if use_llm_for_followups is None else use_llm_for_followups

    if not use_llm:
        mock_result = _mock_static_answer(con, present, question, status)
        if mock_result is not None:
            return mock_result
    return _llm_answer(
        con,
        present,
        question,
        history,
        status,
        use_llm_for_followups=followups_llm,
    )


def _resolve_answer_stream(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
    *,
    use_llm_for_followups: bool | None = None,
):
    """Yield status events in real time; return the final _AnswerResult via StopIteration."""
    if not use_llm:
        if _is_off_topic(question):
            return StaticAnswer(
                off_topic_refusal(question), question, present, skip_follow_ups=True
            )
        if _is_casual_chat(question):
            return StaticAnswer(
                _mock_greeting(question), question, present, skip_follow_ups=True
            )
        if _is_ambiguous(question):
            return StaticAnswer(
                _mock_clarification(question), question, present, skip_follow_ups=True
            )
        if _is_dashboard_help(question):
            return StaticAnswer(
                _mock_dashboard_help(question), question, present, skip_follow_ups=True
            )

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
        rows = _records(df) if err is None else []
        return StaticAnswer(
            text,
            question,
            present,
            visualization=viz,
            sql=sql_used,
            error=err,
            answered_id=plan.get("id"),
            rows=rows,
            plan=plan,
            use_llm_for_followups=False,
        )

    if _is_casual_chat(question):
        return StaticAnswer(
            _mock_greeting(question), question, present, skip_follow_ups=True
        )

    schema = schema_doc(present)
    yield _status_event("planning", question)
    plan_fn, repair_factory, narrate_fn, narrate_stream_fn = make_llm_steps(
        schema, history
    )
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
    followups_llm = use_llm if use_llm_for_followups is None else use_llm_for_followups
    return NarratedAnswer(
        lambda: narrate_stream_fn(question, rows),
        lambda: narrate_fn(question, rows),
        question,
        present,
        visualization=viz,
        sql=sql_used,
        rows=rows,
        plan=plan,
        use_llm_for_followups=followups_llm,
    )


def prepare_answer(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
    *,
    use_llm_for_followups: bool | None = None,
) -> _AnswerResult:
    return _resolve_answer(
        con,
        present,
        question,
        history,
        use_llm,
        use_llm_for_followups=use_llm_for_followups,
    )


def stream_answer_events(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
    *,
    degraded: bool = False,
    use_llm_for_followups: bool | None = None,
):
    """SSE generator: status events during prep, then result.stream()."""
    if degraded:
        yield _status_event("degraded", question)

    followups_llm = False if degraded else use_llm_for_followups
    gen = _resolve_answer_stream(
        con,
        present,
        question,
        history,
        use_llm,
        use_llm_for_followups=followups_llm,
    )
    result = None
    while True:
        try:
            yield next(gen)
        except StopIteration as stop:
            result = stop.value
            break
    if result is not None:
        yield from result.stream()


def answer(
    con,
    present: set[str],
    question: str,
    history: str,
    use_llm: bool,
) -> dict:
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
