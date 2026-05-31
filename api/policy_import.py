"""Extract structured expense policies from free text or PDF content."""

from __future__ import annotations

import base64
import re
import sys
import uuid
from datetime import date
from io import BytesIO
from typing import Any

from pydantic import BaseModel, Field
from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_NOTES_LEN = 200
MAX_NOTES_VALIDATE = 300
SHORT_DOC_CHARS = 4000
CHUNK_TARGET_CHARS = 3500
MAX_TOTAL_CHARS = 80_000
GENERIC_POLICY_NAMES = frozenset({
    "imported expense policy",
    "policy document",
    "expense policy",
    "imported policy",
})

SECTION_HEADING_RE = re.compile(
    r"(?m)^(?:"
    r"#{1,4}\s+\S[^\n]{0,80}|"                      # markdown headings
    r"§\s*\d+[\w.]*\s*[^\n]{0,80}|"
    r"section\s+\d+[\w.]*\s*[^\n]{0,80}|"
    r"\d+[.)](?:\d+[.)]?)*\s+[A-Za-z][^\n]{2,80}|"  # 1. / 1) / 1.2 Title (digit-dot-space)
    r"[A-Z][A-Za-z0-9 /&'-]{3,60}:[^\n]{0,8}|"      # 'Tips & Gratuities:' style sub-heading
    r"[A-Z][A-Z0-9 /&-]{4,60}$"                     # ALL-CAPS heading line
    r")",
    re.I,
)


class PdfValidationError(ValueError):
    """Invalid or unsupported PDF input."""


class PdfTextExtractionError(ValueError):
    """PDF has no extractable text (e.g. scanned image)."""


class PolicyRequirementsModel(BaseModel):
    approval_threshold_cad: float | None = Field(
        default=None,
        description="CAD amount above which pre-approval is required",
    )
    category_limits_cad: dict[str, float] = Field(
        default_factory=dict,
        description="Max CAD per transaction by Brim category",
    )
    restricted_categories: list[str] = Field(
        default_factory=list,
        description="Blocked spend categories",
    )
    restricted_merchants: list[str] = Field(
        default_factory=list,
        description="Blocked merchant name substrings",
    )
    notes: str | None = Field(
        default=None,
        description="Short summary only (max 200 chars), never the full document",
    )


class ExtractedPolicy(BaseModel):
    policy_name: str = Field(
        description="Short unique rule name, e.g. 'Meal limits' or 'Pre-approval threshold'",
    )
    policy_requirements: PolicyRequirementsModel
    effective_date: str = Field(default_factory=lambda: date.today().isoformat())


class PolicyImportResult(BaseModel):
    policies: list[ExtractedPolicy] = Field(
        description="One policy per distinct rule; never one blob for the whole PDF",
    )


IMPORT_SYSTEM = """You extract expense policy rules from company policy documents.
Return MULTIPLE separate policies — one per distinct rule or theme.

Rules for policy_requirements (JSONB for a compliance engine):
- approval_threshold_cad: number (CAD) for pre-approval threshold
- category_limits_cad: map Brim categories to max CAD (Repas Personnel, Repas Client,
  Voyage, Logiciel / IT, Transport Local, Carburant, Autre)
- restricted_categories: blocked categories
- restricted_merchants: blocked merchant substrings (e.g. bar, nightclub)
- notes: ONE short sentence (max 200 characters). NEVER paste the full document.

Extract EVERY distinct rule, even qualitative ones with no dollar amount.
Many real policies are mostly prose: capture rules like alcohol restrictions,
receipt requirements, tip/gratuity caps, no-personal-expenses-on-corporate-card,
falsifying-reports-prohibited, mileage/travel rules. For a rule with no number,
return a policy whose only field is a concise `notes` sentence describing it.
NEVER return a single policy that dumps the entire document into notes — split it.

Examples of correct output:
1) policy_name: "Meal limits" — category_limits_cad: Repas Personnel 75, Repas Client 250,
   notes: "Solo vs client meal caps."
2) policy_name: "Pre-authorization threshold" — approval_threshold_cad: 50,
   notes: "Expenses over $50 require manager pre-authorization; receipts required."
3) policy_name: "Restricted merchants" — restricted_merchants: ["bar", "nightclub"],
   notes: "Alcohol-only venues blocked."
4) policy_name: "Alcohol & entertainment" — notes: "Alcohol only reimbursable when
   dining with a customer; guest names and purpose required."
5) policy_name: "Tips & gratuities" — notes: "Tips up to 15% for services; meal tips
   not reimbursed above 20%."

Split by topic: approval thresholds, meals, travel, software, transport, fuel,
restricted merchants, alcohol, receipts, tips, corporate-card use, report integrity, etc."""

CHUNK_HUMAN = """Extract expense policy rules from THIS FRAGMENT ONLY (not the whole document).
Return zero or more policies. Do not duplicate rules already obvious from other fragments.

Fragment:
{document}"""


def _log(msg: str) -> None:
    print(f"[policy_import] {msg}", file=sys.stderr)


def extract_text_from_pdf(raw: bytes) -> str:
    if not raw:
        raise PdfValidationError("PDF file is empty")
    if len(raw) > MAX_PDF_BYTES:
        raise PdfValidationError(
            f"PDF exceeds maximum size of {MAX_PDF_BYTES // (1024 * 1024)} MB"
        )
    if not raw.lstrip().startswith(b"%PDF"):
        raise PdfValidationError("File is not a valid PDF")

    try:
        reader = PdfReader(BytesIO(raw))
        pages = [
            text.strip()
            for page in reader.pages
            if (text := (page.extract_text() or "")).strip()
        ]
    except Exception as exc:
        raise PdfValidationError(f"Could not read PDF: {exc}") from exc

    content = "\n\n".join(pages).strip()
    if not content:
        raise PdfTextExtractionError(
            "PDF appears scanned or has no extractable text. Paste policy text instead."
        )
    return content


def decode_pdf_base64(pdf_base64: str) -> bytes:
    payload = pdf_base64.strip()
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise PdfValidationError(f"Invalid base64 PDF payload: {exc}") from exc
    return raw


def _make_chat_llm():
    import os

    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs: dict[str, Any] = {
        "model": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "temperature": 0,
    }
    thinking = os.getenv("GEMINI_THINKING", "0")
    if thinking and thinking != "0":
        kwargs["thinking_budget"] = int(thinking)
    return ChatGoogleGenerativeAI(**kwargs)


def _truncate_notes(notes: str | None, max_len: int = MAX_NOTES_LEN) -> str | None:
    if not notes:
        return None
    s = " ".join(notes.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 3].rstrip() + "..."


def _has_structured_requirements(req: dict[str, Any]) -> bool:
    if req.get("approval_threshold_cad") is not None:
        return True
    if req.get("category_limits_cad"):
        return True
    if req.get("restricted_categories"):
        return True
    if req.get("restricted_merchants"):
        return True
    return False


def _policy_row(
    policy_name: str,
    requirements: dict[str, Any],
    effective: str | None = None,
) -> dict[str, Any]:
    req = dict(requirements)
    if req.get("notes"):
        req["notes"] = _truncate_notes(str(req["notes"]))
    return {
        "policy_name": policy_name.strip()[:120] or "Policy rule",
        "policy_requirements": req,
        "effective_date": effective or date.today().isoformat(),
        "active": True,
    }


def split_policy_sections(text: str) -> list[tuple[str, str]]:
    """Split document into (title, body) sections for map extraction."""
    text = text.strip()[:MAX_TOTAL_CHARS]
    if not text:
        return []

    matches = list(SECTION_HEADING_RE.finditer(text))
    if len(matches) < 2:
        if len(text) <= SHORT_DOC_CHARS:
            return [("Expense policy", text)]
        parts = re.split(r"\n{2,}", text)
        sections: list[tuple[str, str]] = []
        buf: list[str] = []
        buf_len = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if buf_len + len(part) > CHUNK_TARGET_CHARS and buf:
                body = "\n\n".join(buf)
                title = (buf[0].split("\n", 1)[0])[:80].strip() or "Policy section"
                sections.append((title, body))
                buf = [part]
                buf_len = len(part)
            else:
                buf.append(part)
                buf_len += len(part)
        if buf:
            body = "\n\n".join(buf)
            title = (buf[0].split("\n", 1)[0])[:80].strip() or "Policy section"
            sections.append((title, body))
        return sections or [("Expense policy", text)]

    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if not block:
            continue
        lines = block.split("\n", 1)
        title = lines[0].strip()[:80] or f"Section {i + 1}"
        body = lines[1].strip() if len(lines) > 1 else block
        if len(body) < 40 and i + 1 < len(matches):
            continue
        sections.append((title, body or block))

    return sections if sections else [("Expense policy", text)]


def _merge_chunks(sections: list[tuple[str, str]]) -> list[str]:
    """Merge small adjacent sections up to CHUNK_TARGET_CHARS for LLM calls."""
    if not sections:
        return []
    chunks: list[str] = []
    current_title = sections[0][0]
    current_parts: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current_title, current_parts, current_len
        if current_parts:
            header = f"## {current_title}\n\n" if current_title else ""
            chunks.append(header + "\n\n".join(current_parts))
        current_parts = []
        current_len = 0

    for title, body in sections:
        block = f"## {title}\n\n{body}" if title else body
        if current_len + len(block) > CHUNK_TARGET_CHARS and current_parts:
            flush()
            current_title = title
        elif not current_parts:
            current_title = title
        current_parts.append(block)
        current_len += len(block)

    flush()
    return chunks


# --------------------------------------------------------------------------- #
# Sentence-level, theme-aware deterministic extraction.
#
# Real expense policies are mostly prose, not numbered lists with dollar caps.
# We segment the document into sentences, classify each by intent
# (approval / limit / restriction) and Brim spend category, and emit one focused
# policy per theme found — numeric (category caps, thresholds) AND qualitative
# (alcohol, tips, receipts, corporate-card use, report integrity, mileage).
# --------------------------------------------------------------------------- #

# $50 / $50.00 / 1,200 CAD / 250 dollars  (number-after form must be a real amount)
_AMOUNT_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d{1,2})?)"
    r"|(?<![\d.])([\d,]{2,}(?:\.\d{1,2})?)\s*(?:\$|cad|dollars?)\b",
    re.I,
)
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%|\b(\d{1,3})\s*percent\b", re.I)

# Keyword -> canonical Brim spend category (must match feature4 mapping).
_CATEGORY_PATTERNS: list[tuple[str, str]] = [
    ("Repas Personnel", r"\bsolo\b|dining alone|personal meal|individual meal|per[- ]?diem|employee meal"),
    ("Repas Client", r"client meal|team meal|business meal|client (?:dinner|lunch)|team (?:dinner|lunch)|entertainment of (?:customers|clients)"),
    ("Voyage", r"\btravel\b|flight|air ?fare|airline|hotel|lodging|accommodation|conference|per night|car rental"),
    ("Logiciel / IT", r"software|subscription|saas|licen[cs]e|\blaptop\b|hardware|\bIT\b"),
    ("Transport Local", r"taxi|ride[- ]?share|\buber\b|\blyft\b|transit|parking|ground transport|local transport|\btoll"),
    ("Carburant", r"\bfuel\b|gas(?:oline)?|petrol|mileage|kilometre|kilometer"),
]

_APPROVAL_INTENT = re.compile(
    r"pre-?auth|pre-?approv|must be approved|require[sd]?[^.]{0,25}(?:approv|authoriz|sign-?off)|need[^.]{0,15}approv",
    re.I,
)
_LIMIT_INTENT = re.compile(
    r"\bcap(?:ped)?\b|\blimit|up to|maximum|\bmax\b|not exceed|no more than|per night|per day|per person|allowance|reimburs(?:able|ed) up to",
    re.I,
)
_RESTRICT_INTENT = re.compile(
    r"prohibit|restrict|not permitted|not (?:be )?reimburs|forbidden|not allowed|never (?:be )?reimburs|\bbanned\b|expressly",
    re.I,
)
# True restricted *venues* only — alcohol-the-beverage is contextual (handled as a note).
_VENUE_RE = re.compile(
    r"\b(bar|nightclub|strip club|casino|liquor store|liquor|cannabis|gambling|tobacco)s?\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?:])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 3]


def _amounts_in(sentence: str) -> list[float]:
    out: list[float] = []
    for m in _AMOUNT_RE.finditer(sentence):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if 5 <= val <= 1_000_000:
            out.append(val)
    return out


def _percents_in(sentence: str) -> list[int]:
    out: list[int] = []
    for m in _PERCENT_RE.finditer(sentence):
        raw = m.group(1) or m.group(2)
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= v <= 100:
            out.append(v)
    return out


def _categories_in(sentence: str) -> list[str]:
    cats: list[str] = []
    for cat, pat in _CATEGORY_PATTERNS:
        if re.search(pat, sentence, re.I) and cat not in cats:
            cats.append(cat)
    return cats


def _clean_note(text: str, max_len: int = MAX_NOTES_LEN) -> str:
    s = " ".join(text.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _find_sentences(
    sentences: list[str], pattern: str, limit: int = 1, prefer: str | None = None
) -> list[str]:
    rx = re.compile(pattern, re.I)
    hits = [s for s in sentences if rx.search(s)]
    if prefer:
        pr = re.compile(prefer, re.I)
        hits.sort(key=lambda s: 0 if pr.search(s) else 1)
    return hits[:limit]


def _analyze(text: str):
    """One pass over the document: collect thresholds, category caps, restrictions."""
    sentences = _sentences(text)
    global_thresholds: list[float] = []
    cat_limits: dict[str, float] = {}
    cat_thresholds: dict[str, list[float]] = {}
    restricted: list[str] = []

    for sent in sentences:
        if _RESTRICT_INTENT.search(sent):
            for m in _VENUE_RE.finditer(sent):
                word = m.group(1).lower()
                if word not in restricted:
                    restricted.append(word)
        amounts = _amounts_in(sent)
        if not amounts:
            continue
        cats = _categories_in(sent)
        if _APPROVAL_INTENT.search(sent):
            if cats:
                for c in cats:
                    cat_thresholds.setdefault(c, []).append(min(amounts))
            else:
                global_thresholds.extend(amounts)
        elif _LIMIT_INTENT.search(sent) and cats:
            amt = min(amounts)
            for c in cats:
                if c not in cat_limits or amt < cat_limits[c]:
                    cat_limits[c] = amt

    return sentences, global_thresholds, cat_limits, cat_thresholds, restricted


def _category_policies(
    cat_limits: dict[str, float], cat_thresholds: dict[str, list[float]]
) -> list[dict[str, Any]]:
    groups = [
        ("Meal limits", ["Repas Personnel", "Repas Client"]),
        ("Travel & lodging", ["Voyage"]),
        ("Software & IT", ["Logiciel / IT"]),
        ("Local transport", ["Transport Local"]),
        ("Fuel", ["Carburant"]),
    ]
    policies: list[dict[str, Any]] = []
    for name, cats in groups:
        limits = {c: cat_limits[c] for c in cats if c in cat_limits}
        thr_amounts = [a for c in cats for a in cat_thresholds.get(c, [])]
        if not limits and not thr_amounts:
            continue
        req: dict[str, Any] = {}
        bits: list[str] = []
        if limits:
            req["category_limits_cad"] = limits
            bits.append("; ".join(f"{c} ${v:g}" for c, v in limits.items()))
        if thr_amounts:
            bits.append(f"approval required above ${min(thr_amounts):g}")
        req["notes"] = _clean_note(f"{name}: {', '.join(bits)}." if bits else name)
        policies.append(_policy_row(name, req))
    return policies


# (name, trigger pattern, preferred-sentence pattern, how many sentences to keep)
_QUALITATIVE_THEMES: list[tuple[str, str, str | None, int]] = [
    ("Receipts required", r"receipt", r"required|before|submit", 1),
    ("Alcohol & entertainment", r"alcohol|alcoholic", r"unless|only|not permitted|customer|client", 1),
    ("Tips & gratuities", r"\btips?\b|gratuit", r"%|percent", 2),
    ("Corporate card use", r"corporate (?:credit )?cards?|personal expense", r"prohibit|personal expense|only the individual", 1),
    ("Expense report integrity", r"falsif|abuse of this|expressly prohibited", r"falsif|prohibit", 1),
    ("Vehicle, mileage & travel", r"mileage|kilometre|kilometer|canada revenue|cra rate|personal vehicle|car rental|traffic[^.]{0,12}ticket", r"reimburs|rate|not (?:pay|reimburs)", 1),
]


def _qualitative_policies(sentences: list[str]) -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = []
    for name, pat, prefer, limit in _QUALITATIVE_THEMES:
        hits = _find_sentences(sentences, pat, limit=limit, prefer=prefer)
        if not hits:
            continue
        note = _clean_note(" ".join(hits))
        if len(note) < 10:
            continue
        policies.append(_policy_row(name, {"notes": note}))
    return policies


def _deterministic_extract(content: str) -> list[dict[str, Any]]:
    """Theme-aware extraction that works on prose policies, not just numbered caps.

    Never invents amounts that are not in the document — if no rule is found it
    emits a grounded summary, not fabricated defaults."""
    sentences, global_thresholds, cat_limits, cat_thresholds, restricted = _analyze(content)
    policies: list[dict[str, Any]] = []

    if global_thresholds:
        thr = min(global_thresholds)
        note = _find_sentences(sentences, _APPROVAL_INTENT.pattern, limit=1, prefer=r"\$|\d")
        note_text = _clean_note(note[0]) if note else f"Expenses at or above ${thr:g} require pre-approval."
        policies.append(_policy_row(
            "Pre-authorization threshold",
            {"approval_threshold_cad": thr, "notes": note_text},
        ))

    policies.extend(_category_policies(cat_limits, cat_thresholds))

    if restricted:
        uniq: list[str] = []
        for r in restricted:
            if r not in uniq:
                uniq.append(r)
        policies.append(_policy_row(
            "Restricted merchants",
            {"restricted_merchants": uniq[:10], "notes": "Blocked venues: " + ", ".join(uniq[:10]) + "."},
        ))

    policies.extend(_qualitative_policies(sentences))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for p in policies:
        key = _normalize_name(p["policy_name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    if deduped:
        _log(f"deterministic: {len(sentences)} sentences -> {len(deduped)} policies")
        return deduped

    summary = _clean_note(content)
    if len(summary) >= 10:
        _log("deterministic: no structured rules -> grounded summary policy")
        return [_policy_row("Expense policy summary", {"notes": summary})]
    return []


def _policy_themes(policy: dict[str, Any]) -> set[str]:
    """Coarse theme tags (structured fields + name/notes keywords) for gap-fill merge."""
    req = policy.get("policy_requirements") or {}
    tags: set[str] = set()
    if req.get("approval_threshold_cad") is not None:
        tags.add("threshold")
    for c in (req.get("category_limits_cad") or {}):
        cl = c.lower()
        if "repas" in cl or "meal" in cl:
            tags.add("meals")
        elif "voyage" in cl or "travel" in cl:
            tags.add("travel")
        elif "logiciel" in cl or "software" in cl:
            tags.add("software")
        elif "transport" in cl:
            tags.add("transport")
        elif "carburant" in cl or "fuel" in cl:
            tags.add("fuel")
    if req.get("restricted_merchants"):
        tags.add("restricted")
    blob = (policy.get("policy_name", "") + " " + (req.get("notes") or "")).lower()
    for kw, tag in [
        ("alcohol", "alcohol"), ("tip", "tips"), ("gratuit", "tips"),
        ("receipt", "receipts"), ("falsif", "integrity"), ("integrity", "integrity"),
        ("corporate card", "card"), ("personal expense", "card"),
        ("mileage", "vehicle"), ("kilomet", "vehicle"), ("vehicle", "vehicle"),
        ("pre-auth", "threshold"), ("pre-approv", "threshold"),
    ]:
        if kw in blob:
            tags.add(tag)
    return tags


def _merge_policies(
    primary: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep `primary` (LLM) and gap-fill themes it missed from `extra` (deterministic)."""
    covered: set[str] = set()
    for p in primary:
        covered |= _policy_themes(p)
    out = list(primary)
    for p in extra:
        themes = _policy_themes(p)
        if themes and not (themes & covered):
            out.append(p)
            covered |= themes
    return out


def _llm_extract_chunk(document: str) -> list[dict[str, Any]]:
    from langchain_core.prompts import ChatPromptTemplate

    chain = ChatPromptTemplate.from_messages([
        ("system", IMPORT_SYSTEM),
        ("human", CHUNK_HUMAN),
    ]) | _make_chat_llm().with_structured_output(PolicyImportResult)

    result: PolicyImportResult = chain.invoke({"document": document[:CHUNK_TARGET_CHARS + 500]})
    out: list[dict[str, Any]] = []
    for p in result.policies:
        out.append({
            "policy_name": p.policy_name,
            "policy_requirements": p.policy_requirements.model_dump(exclude_none=True),
            "effective_date": p.effective_date,
            "active": True,
        })
    return out


def _llm_extract(content: str) -> list[dict[str, Any]]:
    sections = split_policy_sections(content)
    chunks = _merge_chunks(sections)
    _log(f"llm: {len(sections)} sections -> {len(chunks)} chunks")

    merged: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        try:
            part = _llm_extract_chunk(chunk)
            merged.extend(part)
            _log(f"llm chunk {i + 1}/{len(chunks)}: {len(part)} policies")
        except Exception as exc:
            _log(f"llm chunk {i + 1} failed: {exc}")

    if not merged and len(chunks) == 1:
        merged = _llm_extract_chunk(content[:SHORT_DOC_CHARS])

    return merged


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def normalize_and_validate(policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop blob policies, cap notes, dedupe names."""
    out: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}

    for row in policies:
        item = dict(row)
        name = str(item.get("policy_name", "")).strip()
        req = dict(item.get("policy_requirements") or {})

        if req.get("notes"):
            req["notes"] = _truncate_notes(str(req["notes"]))

        notes_len = len(req.get("notes") or "")
        generic = _normalize_name(name) in GENERIC_POLICY_NAMES
        structured = _has_structured_requirements(req)

        if generic and not structured:
            continue
        if notes_len > MAX_NOTES_VALIDATE and not structured:
            continue
        if not structured and notes_len < 10:
            continue

        norm = _normalize_name(name) or "policy rule"
        count = seen_names.get(norm, 0)
        seen_names[norm] = count + 1
        if count > 0:
            name = f"{name} ({count + 1})"

        item["policy_name"] = name
        item["policy_requirements"] = {k: v for k, v in req.items() if v is not None}
        item.setdefault("effective_date", date.today().isoformat())
        item.setdefault("active", True)
        out.append(item)

    return out


def extract_policies_from_text(content: str, use_llm: bool = True) -> list[dict[str, Any]]:
    text = content.strip()
    if not text:
        return []

    # The deterministic engine is always run: it is the offline-safe baseline and,
    # when the LLM is on, it gap-fills any theme the LLM missed (so we never regress).
    deterministic = _deterministic_extract(text)
    policies = deterministic

    if use_llm:
        import os

        if not os.getenv("GOOGLE_API_KEY"):
            _log("llm skipped: GOOGLE_API_KEY not set -> deterministic only")
        else:
            try:
                llm = _llm_extract(text)
                if llm:
                    policies = _merge_policies(llm, deterministic)
                    _log(f"llm ok: {len(llm)} llm + gap-fill -> {len(policies)} policies")
                else:
                    _log("llm returned empty -> deterministic only")
            except Exception as exc:
                _log(f"llm failed: {exc} -> deterministic only")
    else:
        _log("mock_llm=true -> deterministic")

    validated = normalize_and_validate(policies)
    if not validated and deterministic:
        validated = normalize_and_validate(deterministic)
    _log(f"final: {len(validated)} policies")
    return validated


def assign_policy_ids(policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in policies:
        item = dict(row)
        if not item.get("id"):
            item["id"] = f"pol-{uuid.uuid4().hex[:8]}"
        if isinstance(item.get("policy_requirements"), dict):
            item["policy_requirements"] = {
                k: v for k, v in item["policy_requirements"].items() if v is not None
            }
        out.append(item)
    return out
