# Backend prompt: expense reports + PDF export

Paste this to the backend agent/developer. It defines the exact contract the
frontend (`brim-frontend`) relies on for the Reports section so the two stay in
sync. The frontend is tolerant of missing optional fields, but the manager-facing
UI and the PDF export are only fully useful when every field below is provided.

---

## 1. `GET /api/reports?limit=100&offset=0`

Return a paginated page (the frontend also tolerates a raw array as a fallback):

```json
{
  "items": [ /* ExpenseReport[] */ ],
  "has_more": false,
  "limit": 100,
  "offset": 0,
  "total_count": 0
}
```

### `ExpenseReport` item shape

```json
{
  "id": "rep_123",
  "employee_id": "emp_456",
  "event_group_id": "evt_789",
  "title": "Autre — 204-3813708 (2025-09-09…2025-09-21)",
  "date_from": "2025-09-09",
  "date_to": "2025-09-21",
  "total_amount": 411.57,
  "currency": "CAD",
  "status": "ready_for_approval",
  "ai_recommendation": "approve",
  "ai_reasoning": "$411.57 CAD, 0 warning(s) (max weight 0), 0 prior strike(s).",
  "pdf_url": "/api/reports/rep_123/pdf",
  "created_at": "2025-09-22T10:00:00Z",

  "employee_name": "Agathe Potvin",
  "department_name": "Sales",
  "transaction_count": 6,
  "transactions": [
    {
      "date": "2025-09-09",
      "merchant_name": "BB OF BAYTOWN #103",
      "merchant_category": "Autre",
      "city": "BAYTOWN",
      "amount": 119.37
    }
  ]
}
```

#### Field notes

- `total_amount`: number in the report `currency`. The frontend formats it
  (e.g. `$411.57`) using `currency` (defaults to `CAD` if omitted).
- `currency`: ISO 4217 code (e.g. `CAD`, `USD`). Optional; defaults to `CAD`.
- `employee_name` / `department_name`: human-readable, shown on the card header
  and in the PDF. Strongly recommended — without them the card cannot show who
  the report belongs to.
- `transaction_count`: integer. If `transactions` is included, it must match its
  length. If you cannot ship line items yet, still send `transaction_count`.
- `transactions[]`: the line items. Required columns: `date` (`YYYY-MM-DD`),
  `merchant_name`, `merchant_category`, `city`, `amount` (number in `currency`).
  Order chronologically.
- `pdf_url`: see section 3.

### `status` (string enum)

The frontend normalizes case/spacing/hyphens and maps each value to a
manager-friendly label, color, and tooltip. Use one of:

| Value                | UI label            | Meaning the UI communicates                                              |
| -------------------- | ------------------- | ------------------------------------------------------------------------ |
| `draft`              | Draft               | Still being assembled from transactions; not ready for a decision.       |
| `processing`         | Processing          | AI still reviewing; check back shortly.                                  |
| `ready_for_approval` | Ready for approval  | Reviewed by AI, waiting for a manager to sign off / request / reject.    |
| `approved`           | Approved            | A manager approved it; no further action.                                |
| `rejected`           | Rejected            | Rejected and sent back; employee must address the issues.                |

Accepted aliases (normalized to the canonical value): `submitted`,
`pending_approval`, `awaiting_approval` → `ready_for_approval`; `denied`,
`declined` → `rejected`; `generating`, `in_progress` → `processing`. Unknown
values fall back to `draft`.

### `ai_recommendation` (string enum) — required

Exactly one of `approve` | `review` | `deny`. The frontend renders:

| Value     | UI label              | Meaning                                                                  |
| --------- | --------------------- | ------------------------------------------------------------------------ |
| `approve` | AI: Safe to approve   | No policy issues / risky spend; safe to approve as-is.                   |
| `review`  | AI: Needs a quick review | Something worth a second look (amount/category/merchant) before approving. |
| `deny`    | AI: Recommend rejecting | Policy concerns serious enough to recommend rejecting.                   |

`ai_reasoning`: short free-text shown under the recommendation. Keep it concise
and human-readable (1–2 sentences).

---

## 2. `POST /api/reports/generate?mock_llm=<bool>&gap_days=<int>`

Unchanged from today. Body: `{ "event_group_id": string | null }`. Response:

```json
{
  "feature": "reports",
  "model": "...",
  "report_count": 3,
  "expense_reports": [ /* ExpenseReport[] as above */ ],
  "persisted": { "event_groups_updated": 1, "reports_upserted": 3 }
}
```

---

## 3. PDF export — `GET /api/reports/{report_id}/pdf`

The frontend "Export PDF" button downloads from `pdf_url` when present
(resolved against the API origin), otherwise it falls back to
`GET /api/reports/{report_id}/pdf`. Implement this endpoint so either path works.

- Method: `GET`
- Response: `200` with `Content-Type: application/pdf` and the PDF bytes
  (the frontend downloads the response as a blob).
- Recommended: `Content-Disposition: attachment; filename="<report title>.pdf"`.
- Generate on demand if not cached. Errors should return a non-2xx status; the
  frontend surfaces the message in a toast.

### Required PDF layout (match the reference exactly)

```
Expense Report
<title>
Period <date_from> – <date_to>
Total amount <total_amount> <currency>
Status <status>
Employee <employee_name>
Department <department_name>
AI recommendation <ai_recommendation>
AI reasoning <ai_reasoning>

Transactions
Date | Merchant | Category | City | Amount (<currency>)
<one row per transaction, chronological>
```

The transactions table columns must be, in order: Date, Merchant, Category,
City, Amount — matching the `transactions[]` fields above.
