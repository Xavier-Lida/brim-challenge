"""Feature 2 — compliance scan routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.compliance_service import execute_compliance_scan
from api.deps import supabase_client

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.post("/scan")
def scan_compliance(
    mock_llm: bool = Query(False, alias="mock_llm"),
    limit: int | None = Query(None, ge=1),
    replace: bool = Query(True, description="Replace prior flags for scanned transactions"),
    employee_id: str | None = Query(None, description="Scan only this employee's transactions"),
    client=Depends(supabase_client),
) -> dict[str, Any]:
    return execute_compliance_scan(
        client,
        mock_llm=mock_llm,
        limit=limit,
        replace=replace,
        employee_id=employee_id,
    )
