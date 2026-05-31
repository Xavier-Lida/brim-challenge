"""FastAPI dependencies and shared config."""

from __future__ import annotations

import os

from fastapi import HTTPException, Query

from api.supabase_io import get_supabase_client


def cors_origins() -> list[str]:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    base = (os.getenv("APP_BASE_URL") or "").rstrip("/")
    if base and base not in origins:
        origins.append(base)
    return origins


def use_llm_from_query(mock_llm: bool = Query(False, alias="mock_llm")) -> bool:
    return not mock_llm


def supabase_client():
    try:
        return get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
