import { apiFetch } from "@/lib/api/client";
import { mockLlm } from "@/lib/api/config";
import type { Policy, PolicyImportDraft, PolicyRequirements } from "@/lib/types/brim";

export async function getPolicies(): Promise<Policy[]> {
  return apiFetch<Policy[]>("/api/policies");
}

export async function createPolicy(data: {
  policy_name: string;
  policy_requirements: PolicyRequirements;
  effective_date?: string;
  active?: boolean;
}): Promise<Policy> {
  return apiFetch<Policy>("/api/policies", {
    method: "POST",
    body: data,
  });
}

export async function updatePolicy(
  id: string,
  data: Partial<{
    policy_name: string;
    policy_requirements: PolicyRequirements;
    effective_date: string;
    active: boolean;
  }>
): Promise<Policy> {
  return apiFetch<Policy>(`/api/policies/${id}`, {
    method: "PATCH",
    body: data,
  });
}

export async function deletePolicy(id: string): Promise<{ id: string; deleted: boolean }> {
  return apiFetch<{ id: string; deleted: boolean }>(`/api/policies/${id}`, {
    method: "DELETE",
  });
}

export async function importPoliciesPreview(input: {
  content?: string;
  pdf_base64?: string;
  mock_llm?: boolean;
}): Promise<{ policies: PolicyImportDraft[] }> {
  const body =
    input.pdf_base64 != null && input.pdf_base64 !== ""
      ? { pdf_base64: input.pdf_base64 }
      : { content: input.content ?? "" };

  return apiFetch<{ policies: PolicyImportDraft[] }>("/api/policies/import", {
    method: "POST",
    params: { mock_llm: input.mock_llm ?? mockLlm },
    body,
  });
}

export async function confirmPolicyImport(
  policies: PolicyImportDraft[]
): Promise<{ count: number; policies: Policy[] }> {
  return apiFetch<{ count: number; policies: Policy[] }>(
    "/api/policies/import/confirm",
    {
      method: "POST",
      body: { policies },
    }
  );
}
