"""Feature 1 — Brim Assistant API route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import supabase_client
from feature1 import answer, build_db_from_supabase, format_history

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class HistoryTurn(BaseModel):
    question: str
    summary: str | None = None
    text: str | None = None


class AssistantBody(BaseModel):
    question: str
    history: list[HistoryTurn] = Field(default_factory=list)


@router.post("")
def ask_assistant(
    body: AssistantBody,
    mock_llm: bool = Query(False, alias="mock_llm"),
    limit: int | None = Query(None, ge=1),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    use_llm = not mock_llm
    history = format_history([t.model_dump() for t in body.history])

    try:
        con, present = build_db_from_supabase(client, limit=limit)
        try:
            result = answer(con, present, question, history, use_llm)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        try:
            con, present = build_db_from_supabase(client, limit=limit)
            try:
                result = answer(con, present, question, history, use_llm=False)
            finally:
                con.close()
        except Exception as inner:
            raise HTTPException(status_code=500, detail=str(inner)) from exc

    return {
        "text": result["text"],
        "visualization": result["visualization"],
        "followUpSuggestions": result["followUpSuggestions"],
        "sql": result.get("sql"),
    }
