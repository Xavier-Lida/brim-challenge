"""Feature 1 — Brim Assistant API route."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import supabase_client
from feature1 import (
    _status_event,
    answer,
    build_db_from_supabase,
    format_history,
    stream_answer_events,
)

logger = logging.getLogger("brim.assistant")

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
        logger.warning("assistant LLM path failed, degrading to mock: %s", exc)
        try:
            con, present = build_db_from_supabase(client, limit=limit)
            try:
                result = answer(con, present, question, history, use_llm=False)
                result["_degraded"] = True
            finally:
                con.close()
        except Exception as inner:
            raise HTTPException(status_code=500, detail=str(inner)) from exc

    return {
        "text": result["text"],
        "visualization": result.get("visualization"),
        "followUpSuggestions": result["followUpSuggestions"],
        "sql": result.get("sql"),
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/stream")
def ask_assistant_stream(
    body: AssistantBody,
    mock_llm: bool = Query(False, alias="mock_llm"),
    limit: int | None = Query(None, ge=1),
    client=Depends(supabase_client),
) -> StreamingResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    use_llm = not mock_llm
    history = format_history([t.model_dump() for t in body.history])

    def event_stream() -> Iterator[str]:
        con = None
        present: set[str] | None = None
        events = None
        try:
            yield _sse(_status_event("loading_data", question))
            con, present = build_db_from_supabase(client, limit=limit)
            events = stream_answer_events(con, present, question, history, use_llm)
        except Exception as exc:  # noqa: BLE001 — prep / plan / SQL failed
            logger.warning("assistant stream LLM path failed, degrading to mock: %s", exc)
            try:
                if con is None or present is None:
                    yield _sse(_status_event("loading_data", question))
                    con, present = build_db_from_supabase(client, limit=limit)
                events = stream_answer_events(
                    con, present, question, history, use_llm=False, degraded=True,
                )
            except Exception as inner:  # noqa: BLE001
                yield _sse({"type": "error", "message": str(inner)})
                yield _sse({"type": "done"})
                return

        try:
            if events is not None:
                for event in events:
                    yield _sse(event)
        except Exception as exc:  # noqa: BLE001 — narration stream failed mid-flight
            logger.warning("assistant narration stream failed: %s", exc)
            yield _sse({"type": "error", "message": str(exc)})
            yield _sse({"type": "done"})
        finally:
            if con is not None:
                con.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
