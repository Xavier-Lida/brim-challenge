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

# Debug indicator: prefix shown on any answer that did NOT come from a live
# Gemini call (explicit mock, or LLM failure that silently degraded to mock).
_MOCK_TAG = "[M] "


def _engine_of(mock_llm: bool, degraded: bool) -> str:
    """gemini = real LLM answered · mock = mock_llm forced · degraded = LLM failed → mock."""
    if mock_llm:
        return "mock"
    return "degraded" if degraded else "gemini"


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

    engine = _engine_of(mock_llm, bool(result.get("_degraded")))
    text = result["text"]
    if engine != "gemini":
        text = _MOCK_TAG + text

    return {
        "text": text,
        "visualization": result.get("visualization"),
        "followUpSuggestions": result["followUpSuggestions"],
        "sql": result.get("sql"),
        "engine": engine,
        "mock": engine != "gemini",
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
        tagged = {"done": False}

        def pump(events, engine):
            """Relay events, prefixing the first text chunk with [M] when not live Gemini."""
            for event in events:
                if (engine != "gemini" and not tagged["done"]
                        and event.get("type") == "text_delta"):
                    event = {**event, "delta": _MOCK_TAG + event.get("delta", "")}
                    tagged["done"] = True
                yield _sse(event)

        try:
            yield _sse(_status_event("loading_data", question))
            con, present = build_db_from_supabase(client, limit=limit)
            engine = _engine_of(mock_llm, degraded=False)
            try:
                yield from pump(
                    stream_answer_events(
                        con,
                        present,
                        question,
                        history,
                        use_llm,
                    ),
                    engine,
                )
            except Exception as exc:  # noqa: BLE001 — plan / SQL / narration failed
                # Live Gemini failed before streaming any text → degrade to a tagged mock,
                # mirroring the sync route. If text already streamed, surface the error.
                if not use_llm or tagged["done"]:
                    logger.warning("assistant narration stream failed: %s", exc)
                    yield _sse({"type": "error", "message": str(exc)})
                    yield _sse({"type": "done"})
                    return
                logger.warning("assistant stream LLM path failed, degrading to mock: %s", exc)
                yield from pump(
                    stream_answer_events(
                        con,
                        present,
                        question,
                        history,
                        use_llm=False,
                        degraded=True,
                    ),
                    "degraded",
                )
        except Exception as inner:  # noqa: BLE001 — data load failed; nothing to degrade to
            yield _sse({"type": "error", "message": str(inner)})
            yield _sse({"type": "done"})
        finally:
            if con is not None:
                con.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
