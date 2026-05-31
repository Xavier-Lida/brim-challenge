# Backend: pagination flags & reports

The frontend expects paginated responses (with client-side fallback if the API still returns a raw array).

## `GET /api/flags?limit=100&offset=0`

```json
{
  "items": [],
  "has_more": false,
  "limit": 100,
  "offset": 0,
  "unread_count": 0
}
```

- `unread_count`: global count of flags where `reviewed === false` (for sidebar badge).
- Sort by `weight` descending (recommended).

## `GET /api/reports?limit=100&offset=0`

```json
{
  "items": [],
  "has_more": false,
  "limit": 100,
  "offset": 0,
  "total_count": 0
}
```

Until the backend is updated, the frontend normalizes array responses in `lib/api/pagination.ts` (slices by limit/offset on the client).
