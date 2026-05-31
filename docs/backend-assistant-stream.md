# Assistant streaming API contract

Backend base URL: `BACKEND_URL` (default `http://127.0.0.1:8000`).

Enable SSE on the frontend with:

```bash
NEXT_PUBLIC_ASSISTANT_STREAM=true
```

When disabled or when the stream endpoint fails, the client falls back to `POST /api/assistant` and simulates typing word-by-word.

---

## `POST /api/assistant`

Existing JSON endpoint. Request body:

```json
{
  "question": "Show spend by department this quarter",
  "history": [
    { "question": "...", "summary": "..." }
  ]
}
```

Query param: `mock_llm=true|false`

Response:

```json
{
  "text": "Markdown-friendly answer...",
  "visualization": {
    "type": "bar",
    "title": "Q2 spend by department",
    "data": { "series": [{ "name": "Sales", "value": 256431.43 }] }
  },
  "followUpSuggestions": ["...", "..."],
  "sql": "SELECT ..."
}
```

`sql` is accepted but **not rendered** in the Brim UI.

---

## `POST /api/assistant/stream`

Server-Sent Events endpoint for real-time assistant responses. Implemented in
`api/routes/assistant.py`. Planning + SQL execution is a blocking prefix; only the
LLM narration is streamed token-by-token. The mock engine emits its fixed text as a
single `text_delta`.

### Request

```
POST /api/assistant/stream?mock_llm=true
Content-Type: application/json
Accept: text/event-stream
```

Body: same as `/api/assistant`.

### Response

`Content-Type: text/event-stream`

Each event is a single SSE `data:` line containing JSON:

```
data: {"type":"status","phase":"loading_data","message":"Loading data…"}

data: {"type":"status","phase":"planning","message":"Analyzing your question…"}

data: {"type":"status","phase":"running_query","message":"Querying spend data…"}

data: {"type":"visualization","visualization":{"type":"bar","title":"...","data":{...}}}

data: {"type":"status","phase":"writing","message":"Writing the answer…"}

data: {"type":"text_delta","delta":"Here "}

data: {"type":"follow_up","suggestions":["Show flags","Compare Q1"]}

data: {"type":"done"}
```

### Event types

| type | payload | UI behavior |
|---|---|---|
| `status` | `{ "phase": string, "message": string }` | Update the single activity line in the streaming bubble (replaced on each event) |
| `text_delta` | `{ "delta": string }` | Append to streaming assistant bubble; clears activity line |
| `visualization` | `{ "visualization": Visualization }` | Switch layout to split; render chart in center stage |
| `follow_up` | `{ "suggestions": FollowUpSuggestion[] }` | Show clickable chips under last message |
| `done` | — | Finalize message (`streaming: false`) |
| `error` | `{ "message": string }` | Show error text; finalize message |

Status `phase` values: `loading_data`, `planning`, `running_query`, `repairing_sql`, `writing`, `degraded`. Messages are localized (FR/EN) from the user question language.

### Server event order

1. Emit one or more `status` events during data load, planning, and SQL execution
2. Emit `visualization` when structured data is ready (omitted for scoped/text-only replies)
3. Emit `status` with phase `writing` before narration (LLM path only)
4. Stream `text_delta` events (single chunk for the mock engine; token stream for Gemini)
5. Emit `follow_up` with exactly 3 contextual suggestions
6. Emit `done` (or `error` then `done` on failure)

### Follow-up suggestions

Each suggestion is either a legacy string (chip text = prompt) or a structured object:

```json
{
  "label": "Mélanie — by category",
  "prompt": "Show Mélanie Charron's spend breakdown by category",
  "hint": "Drill into the top spender from your last answer."
}
```

- Generated from the last question + SQL rows + visualization (Gemini when `mock_llm=false`, heuristics when mock/degraded).
- Three angles: narrow (drill into entity), pivot (different dimension), broaden (wider lens / compliance / trend).
- The UI sends `prompt` on chip click, not `label`.

### Date ranges

There is no session toolbar filter. Table `tx` is the full loaded dataset. Date
predicates are added only when the user names a period in their question (e.g. « this
quarter », « last month »). Vague spend questions without a period use all loaded data.

Deterministic mock routes include: `top_employees`, `spend_by_department`, `spend_by_category`, `spend_by_city`, `total_spend`, plus existing compliance/budget capabilities.

---

## Visualization types

The backend (`feature1.build_visualization`) owns column selection and emits a
canonical `data` shape per type. The frontend normalizers consume the canonical
shape and stay tolerant of legacy payloads during transition.

| type | canonical `data` shape |
|---|---|
| `bar` | `{ "series": { "name": string, "value": number }[] }` |
| `line` | `{ "series": { "name": string, "value": number }[] }` |
| `pie` | `{ "segments": { "name": string, "value": number }[] }` |
| `table` | `{ "columns": string[], "rows": string[][] }` |
| `kpi` | `{ "value": string, "label": string, "change"?: string }` |

Legacy shapes still accepted by the normalizers: `{ labels, values }` and row-object
arrays (`Record<string, unknown>[]`) for `bar`/`line`/`pie`/`table`.

---

## Frontend persistence

Conversation state is stored in `localStorage` key `brim-assistant-session`:

- messages (including `streaming` flag)
- layout mode (`centered` | `split`)
- active visualization message id

---

## FastAPI implementation

See `api/routes/assistant.py`. The route builds an answer handler via
`feature1.prepare_answer(...)` (which runs PLAN + SQL up front), then iterates the
handler's `.stream()` generator, serializing each event as an SSE `data:` line:

```python
from fastapi.responses import StreamingResponse

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

@router.post("/stream")
def ask_assistant_stream(body, mock_llm=False, client=Depends(supabase_client)):
    def event_stream():
        con, present = build_db_from_supabase(client)
        try:
            result = prepare_answer(con, present, question, history, not mock_llm)
            for event in result.stream():   # visualization -> text_delta* -> follow_up -> done
                yield _sse(event)
        finally:
            con.close()
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

If the LLM planning path raises, the route degrades to the mock engine and logs a
warning. CORS already allows the Next.js origin (`main.py`).
