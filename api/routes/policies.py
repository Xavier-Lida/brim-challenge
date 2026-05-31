"""Policy CRUD and import routes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import supabase_client
from api.policy_import import (
    PdfTextExtractionError,
    PdfValidationError,
    assign_policy_ids,
    decode_pdf_base64,
    extract_policies_from_text,
    extract_text_from_pdf,
)
from api.supabase_io import (
    delete_policy as delete_policy_row,
    insert_policies,
    list_policies,
    upsert_policy,
)

router = APIRouter(prefix="/api/policies", tags=["policies"])


class PolicyRequirementsBody(BaseModel):
    approval_threshold_cad: float | None = None
    category_limits_cad: dict[str, float] = Field(default_factory=dict)
    restricted_categories: list[str] = Field(default_factory=list)
    restricted_merchants: list[str] = Field(default_factory=list)
    notes: str | None = None


class PolicyBody(BaseModel):
    policy_name: str
    policy_requirements: PolicyRequirementsBody
    effective_date: str = Field(default_factory=lambda: date.today().isoformat())
    active: bool = True


class PolicyPatchBody(BaseModel):
    policy_name: str | None = None
    policy_requirements: PolicyRequirementsBody | None = None
    effective_date: str | None = None
    active: bool | None = None


class PolicyImportBody(BaseModel):
    content: str | None = None
    pdf_base64: str | None = None


class PolicyImportConfirmBody(BaseModel):
    policies: list[PolicyBody]


@router.get("")
def get_policies(client=Depends(supabase_client)) -> list[dict[str, Any]]:
    return list_policies(client)


@router.post("")
def create_policy(body: PolicyBody, client=Depends(supabase_client)) -> dict[str, Any]:
    row = {
        "id": f"pol-{uuid.uuid4().hex[:8]}",
        "policy_name": body.policy_name,
        "policy_requirements": body.policy_requirements.model_dump(exclude_none=True),
        "effective_date": body.effective_date,
        "active": body.active,
    }
    return upsert_policy(client, row)


@router.patch("/{policy_id}")
def update_policy(
    policy_id: str,
    body: PolicyPatchBody,
    client=Depends(supabase_client),
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.policy_name is not None:
        updates["policy_name"] = body.policy_name
    if body.policy_requirements is not None:
        updates["policy_requirements"] = body.policy_requirements.model_dump(exclude_none=True)
    if body.effective_date is not None:
        updates["effective_date"] = body.effective_date
    if body.active is not None:
        updates["active"] = body.active
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    res = client.table("policies").update(updates).eq("id", policy_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return res.data[0]


@router.delete("/{policy_id}")
def delete_policy(policy_id: str, client=Depends(supabase_client)) -> dict[str, Any]:
    try:
        delete_policy_row(client, policy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": policy_id, "deleted": True}


@router.post("/import")
def import_policies_preview(
    body: PolicyImportBody,
    mock_llm: bool = Query(False, alias="mock_llm"),
) -> dict[str, Any]:
    has_pdf = bool(body.pdf_base64 and body.pdf_base64.strip())
    has_content = bool(body.content and body.content.strip())

    if has_pdf and has_content:
        raise HTTPException(
            status_code=400,
            detail="Provide either pdf_base64 or content, not both",
        )
    if not has_pdf and not has_content:
        raise HTTPException(status_code=400, detail="Provide content or pdf_base64")

    if has_pdf:
        try:
            raw = decode_pdf_base64(body.pdf_base64 or "")
            content = extract_text_from_pdf(raw)
        except PdfValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PdfTextExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        content = (body.content or "").strip()

    use_llm = not mock_llm
    policies = assign_policy_ids(extract_policies_from_text(content, use_llm=use_llm))
    if not policies:
        raise HTTPException(
            status_code=422,
            detail="No policy rules could be extracted from the document",
        )
    return {"policies": policies, "count": len(policies)}


@router.post("/import/confirm")
def import_policies_confirm(
    body: PolicyImportConfirmBody,
    client=Depends(supabase_client),
) -> dict[str, Any]:
    rows = [
        {
            "id": f"pol-{uuid.uuid4().hex[:8]}",
            "policy_name": p.policy_name,
            "policy_requirements": p.policy_requirements.model_dump(exclude_none=True),
            "effective_date": p.effective_date,
            "active": p.active,
        }
        for p in body.policies
    ]
    inserted = insert_policies(client, rows)
    return {"count": len(inserted), "policies": inserted}
