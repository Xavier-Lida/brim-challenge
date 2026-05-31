"""Extract structured expense policies from free text or PDF content."""

from __future__ import annotations

import base64
import re
import uuid
from datetime import date
from io import BytesIO
from typing import Any

from pydantic import BaseModel, Field
from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


class PdfValidationError(ValueError):
    """Invalid or unsupported PDF input."""


class PdfTextExtractionError(ValueError):
    """PDF has no extractable text (e.g. scanned image)."""


class PolicyRequirementsModel(BaseModel):
    approval_threshold_cad: float | None = None
    category_limits_cad: dict[str, float] = Field(default_factory=dict)
    restricted_categories: list[str] = Field(default_factory=list)
    restricted_merchants: list[str] = Field(default_factory=list)
    notes: str | None = None


class ExtractedPolicy(BaseModel):
    policy_name: str
    policy_requirements: PolicyRequirementsModel
    effective_date: str = Field(default_factory=lambda: date.today().isoformat())


class PolicyImportResult(BaseModel):
    policies: list[ExtractedPolicy]


IMPORT_SYSTEM = """You extract expense policy rules from company policy documents.
Return one or more policies with structured JSONB requirements that a compliance engine can use.

Use these keys in policy_requirements:
- approval_threshold_cad: number (CAD) above which pre-approval is required
- category_limits_cad: object mapping Brim spend categories to max CAD per transaction
  Known categories: Repas Personnel, Repas Client, Voyage, Logiciel / IT, Autre
- restricted_categories: list of blocked spend categories
- restricted_merchants: list of merchant name substrings to block
- notes: free-text summary for LLM context

Split distinct rules into separate policies when they have different names/thresholds."""


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


def _deterministic_extract(content: str) -> list[dict[str, Any]]:
    """Regex fallback when Gemini is unavailable."""
    policies: list[dict[str, Any]] = []
    threshold_match = re.search(
        r"(?:pre[- ]?approval|approval|seuil)[^\d]{0,40}(\d{2,5})\s*(?:\$|CAD)?",
        content,
        re.I,
    )
    meal_match = re.search(
        r"(?:solo|individual|personal)\s+meal[^\d]{0,30}(\d{2,3})\s*(?:\$|CAD)?",
        content,
        re.I,
    )
    team_match = re.search(
        r"(?:team|client)\s+meal[^\d]{0,30}(\d{2,3})\s*(?:\$|CAD)?",
        content,
        re.I,
    )

    requirements: dict[str, Any] = {"notes": content[:500].strip()}
    if threshold_match:
        requirements["approval_threshold_cad"] = float(threshold_match.group(1))
    category_limits: dict[str, float] = {}
    if meal_match:
        category_limits["Repas Personnel"] = float(meal_match.group(1))
    if team_match:
        category_limits["Repas Client"] = float(team_match.group(1))
    if category_limits:
        requirements["category_limits_cad"] = category_limits

    policies.append({
        "policy_name": "Imported expense policy",
        "policy_requirements": requirements,
        "effective_date": date.today().isoformat(),
        "active": True,
    })
    return policies


def extract_policies_from_text(content: str, use_llm: bool = True) -> list[dict[str, Any]]:
    text = content.strip()
    if not text:
        return []

    if not use_llm:
        return _deterministic_extract(text)

    try:
        from langchain_core.prompts import ChatPromptTemplate

        chain = ChatPromptTemplate.from_messages([
            ("system", IMPORT_SYSTEM),
            ("human", "{document}"),
        ]) | _make_chat_llm().with_structured_output(PolicyImportResult)

        result: PolicyImportResult = chain.invoke({"document": text[:12000]})
        out: list[dict[str, Any]] = []
        for p in result.policies:
            out.append({
                "policy_name": p.policy_name,
                "policy_requirements": p.policy_requirements.model_dump(exclude_none=True),
                "effective_date": p.effective_date,
                "active": True,
            })
        return out or _deterministic_extract(text)
    except Exception:
        return _deterministic_extract(text)


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
