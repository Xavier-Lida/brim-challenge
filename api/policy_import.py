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
    r"§\s*\d+[\w.]*\s*[^\n]{0,80}|"
    r"section\s+\d+[\w.]*\s*[^\n]{0,80}|"
    r"\d+(?:\.\d+){0,2}\s+[A-Z][^\n]{3,80}|"
    r"[A-Z][A-Z0-9\s/&-]{4,60}$"
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

Each policy MUST include at least one structured field (not notes alone).
NEVER return a single policy that dumps the entire document into notes.

Examples of correct output:
1) policy_name: "Meal limits" — category_limits_cad: Repas Personnel 75, Repas Client 250,
   notes: "Solo vs client meal caps."
2) policy_name: "Pre-approval threshold" — approval_threshold_cad: 500,
   notes: "Purchases at or above $500 need approval."
3) policy_name: "Restricted merchants" — restricted_merchants: ["bar", "nightclub"],
   notes: "Alcohol-only venues blocked."

Split by topic: meals, travel, software, approval thresholds, restricted merchants, etc."""

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
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
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


def _extract_requirements_from_section(section_text: str) -> dict[str, Any]:
    """Regex extraction of structured fields from one section."""
    req: dict[str, Any] = {}
    threshold = re.search(
        r"(?:pre[- ]?approval|approval|seuil|threshold)[^\d]{0,50}(\d{2,5})\s*(?:\$|CAD)?",
        section_text,
        re.I,
    )
    if threshold:
        req["approval_threshold_cad"] = float(threshold.group(1))

    solo = re.search(
        r"(?:solo|individual|personal|repas\s+personnel)[^\d]{0,40}(\d{2,3})\s*(?:\$|CAD)?",
        section_text,
        re.I,
    )
    team = re.search(
        r"(?:team|client|repas\s+client)[^\d]{0,40}(\d{2,3})\s*(?:\$|CAD)?",
        section_text,
        re.I,
    )
    travel = re.search(
        r"(?:trip|travel|voyage|conference)[^\d]{0,40}(\d{3,5})\s*(?:\$|CAD)?",
        section_text,
        re.I,
    )
    limits: dict[str, float] = {}
    if solo:
        limits["Repas Personnel"] = float(solo.group(1))
    if team:
        limits["Repas Client"] = float(team.group(1))
    if travel:
        limits["Voyage"] = float(travel.group(1))
    if limits:
        req["category_limits_cad"] = limits

    merchants: list[str] = []
    for m in re.finditer(
        r"(?:bar|nightclub|casino|liquor|adult)[^\n]{0,30}",
        section_text,
        re.I,
    ):
        word = m.group(0).split()[0].lower()
        if word and word not in merchants:
            merchants.append(word)
    if merchants:
        req["restricted_merchants"] = merchants[:10]

    summary = " ".join(section_text.split())
    if summary:
        req["notes"] = _truncate_notes(summary[:MAX_NOTES_LEN])
    return req


def _deterministic_extract(content: str) -> list[dict[str, Any]]:
    """Multi-policy regex fallback when Gemini is unavailable."""
    sections = split_policy_sections(content)
    policies: list[dict[str, Any]] = []

    for title, body in sections:
        req = _extract_requirements_from_section(body)
        if not _has_structured_requirements(req):
            continue
        name = title.strip()
        if len(name) > 60 or (name.isupper() and len(name) > 20):
            name = name.title()[:60]
        policies.append(_policy_row(name, req))

    if policies:
        _log(f"deterministic: {len(sections)} sections -> {len(policies)} policies")
        return policies

    global_req = _extract_requirements_from_section(content)
    if global_req.get("approval_threshold_cad") is not None:
        policies.append(_policy_row("Pre-approval threshold", {
            "approval_threshold_cad": global_req["approval_threshold_cad"],
            "notes": global_req.get("notes") or "Pre-approval threshold from policy document.",
        }))
    limits = global_req.get("category_limits_cad") or {}
    if limits:
        policies.append(_policy_row("Meal and category limits", {
            "category_limits_cad": limits,
            "notes": "Per-category spending limits.",
        }))
    if global_req.get("restricted_merchants"):
        policies.append(_policy_row("Restricted merchants", {
            "restricted_merchants": global_req["restricted_merchants"],
            "notes": "Blocked merchant types.",
        }))

    if not policies:
        policies = [
            _policy_row("Pre-approval threshold", {
                "approval_threshold_cad": 500.0,
                "notes": "Default threshold; refine after import.",
            }),
            _policy_row("Meal limits", {
                "category_limits_cad": {"Repas Personnel": 75.0, "Repas Client": 250.0},
                "notes": "Default meal caps; refine after import.",
            }),
        ]
        _log("deterministic: no rules found, using defaults")
    else:
        _log(f"deterministic: document-wide -> {len(policies)} policies")
    return policies


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

    policies: list[dict[str, Any]] = []

    if use_llm:
        import os

        if not os.getenv("GOOGLE_API_KEY"):
            _log("llm skipped: GOOGLE_API_KEY not set -> deterministic")
            policies = _deterministic_extract(text)
        else:
            try:
                policies = _llm_extract(text)
                if policies:
                    _log(f"llm ok: {len(policies)} policies before validation")
                else:
                    _log("llm returned empty -> deterministic fallback")
                    policies = _deterministic_extract(text)
            except Exception as exc:
                _log(f"llm failed: {exc} -> deterministic fallback")
                policies = _deterministic_extract(text)
    else:
        _log("mock_llm=true -> deterministic")
        policies = _deterministic_extract(text)

    validated = normalize_and_validate(policies)
    if not validated and policies:
        validated = normalize_and_validate(_deterministic_extract(text))
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
