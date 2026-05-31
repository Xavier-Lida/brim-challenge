"""Load Brim Assistant narration rules from Markdown."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RULES_PATH = _REPO_ROOT / "prompts" / "assistant-narrate-rules.md"

_narrate_rules_cache: str | None = None


def narrate_rules_path() -> Path:
    raw = os.getenv("ASSISTANT_NARRATE_RULES_PATH", "prompts/assistant-narrate-rules.md")
    path = Path(raw)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path


def load_narrate_rules(*, reload: bool = False) -> str:
    """Return narration rules markdown; cached after first successful load."""
    global _narrate_rules_cache
    if _narrate_rules_cache is not None and not reload:
        return _narrate_rules_cache

    path = narrate_rules_path()
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Assistant narrate rules not found at %s", path)
        _narrate_rules_cache = ""
        return _narrate_rules_cache

    _narrate_rules_cache = text
    return _narrate_rules_cache


def build_narrate_system(base: str) -> str:
    rules = load_narrate_rules()
    if not rules:
        return base
    return f"{base}\n\n---\nAdditional rules:\n{rules}"
