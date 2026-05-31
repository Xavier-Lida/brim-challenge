"""Smoke-test all four Brim pipelines against a running backend.

Usage (from anywhere, no deps):
    py smoke_test.py                      # hits the deployed server, mock_llm=true
    py smoke_test.py --gemini             # mock_llm=false  -> exercises Gemini
    py smoke_test.py --base http://127.0.0.1:8000   # test a local backend

Mutating calls (compliance scan, approvals run, reports generate) are the
pipelines themselves — they write to Supabase. That's expected; re-runs are
designed to be idempotent (flags/reports are replaced or de-duplicated).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

OK = "[ OK ]"
FAIL = "[FAIL]"


def call(base: str, method: str, path: str, *, params=None, body=None, timeout=180):
    url = base.rstrip("/") + path
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode({k: str(v).lower() if isinstance(v, bool) else v
                                for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode() or "null")
            return r.status, payload, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], time.time() - t0
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", time.time() - t0


def summarize(payload) -> str:
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    if isinstance(payload, dict):
        for k in ("count", "status", "text"):
            if k in payload:
                v = payload[k]
                return f"{k}={str(v)[:90]}"
        return "keys=" + ",".join(list(payload)[:6])
    return str(payload)[:90]


def validate_policy_checks(payload) -> tuple[bool, str]:
    if not isinstance(payload, list) or not payload:
        return False, "empty approvals list"
    checks = payload[0].get("policy_checks")
    if not isinstance(checks, list) or not checks:
        return False, "policy_checks missing or empty"
    required = {"policy_id", "policy_name", "status"}
    for check in checks:
        if not required.issubset(check.keys()):
            return False, f"check missing keys: {check}"
        if check["status"] not in ("passed", "failed"):
            return False, f"invalid status: {check.get('status')}"
    return True, f"{len(checks)} policy check(s)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://149.28.43.72")
    ap.add_argument("--gemini", action="store_true", help="set mock_llm=false")
    args = ap.parse_args()

    mock = not args.gemini
    m = {"mock_llm": mock}
    mode = "GEMINI (mock_llm=false)" if args.gemini else "MOCK (mock_llm=true)"
    print(f"\nBrim pipeline smoke test -> {args.base}   mode: {mode}\n" + "-" * 64)

    checks = [
        ("health",                 "GET",  "/health",                 None, None),
        ("data: policies",         "GET",  "/api/policies",           None, None),
        ("data: transactions",     "GET",  "/api/transactions",       None, None),
        ("F1 assistant",           "POST", "/api/assistant",          m,
            {"question": "What are the top 5 merchants by total spend?", "history": []}),
        ("F2 compliance scan",     "POST", "/api/compliance/scan",    {**m, "limit": 50}, None),
        ("F3 approvals run",       "POST", "/api/approvals/run",      m, None),
        ("F3 approvals list",      "GET",  "/api/approvals",          None, None),
        ("F4 reports generate",    "POST", "/api/reports/generate",   m, {}),
        ("flags",                  "GET",  "/api/flags",              None, None),
        ("notifications",          "GET",  "/api/notifications",      None, None),
    ]

    failures = 0
    approvals_payload = None
    for name, method, path, params, body in checks:
        status, payload, dt = call(args.base, method, path, params=params, body=body)
        ok = status is not None and 200 <= status < 300
        if not ok:
            failures += 1
        if name == "F3 approvals list" and ok:
            approvals_payload = payload
        tag = OK if ok else FAIL
        print(f"{tag} {name:22} {str(status):>4}  {dt:5.1f}s  {summarize(payload)}")

    if approvals_payload is not None:
        ok, detail = validate_policy_checks(approvals_payload)
        if not ok:
            failures += 1
        tag = OK if ok else FAIL
        print(f"{tag} {'policy_checks':22} {'':>4}        {detail}")

    print("-" * 64)
    print(f"{'ALL PASSED' if not failures else str(failures) + ' FAILED'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
