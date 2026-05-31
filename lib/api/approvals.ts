import { apiFetch } from "@/lib/api/client";
import { mockLlm } from "@/lib/api/config";
import { normalizeApprovalsPage } from "@/lib/api/pagination";
import type { ApprovalRequest, ApprovalStatus } from "@/lib/types/brim";

export const APPROVALS_PAGE_SIZE = 50;

export function getApprovals(params?: { limit?: number; offset?: number }) {
  const limit = params?.limit ?? APPROVALS_PAGE_SIZE;
  const offset = params?.offset ?? 0;
  return apiFetch<unknown>("/api/approvals", {
    params: { limit, offset },
  }).then((data) => normalizeApprovalsPage(data, limit, offset));
}

export function decideApproval(
  approvalId: string,
  body: { status: ApprovalStatus; approver_id?: string | null }
) {
  return apiFetch<{
    approval_id: string;
    status: ApprovalStatus;
    transaction_id: string;
  }>(`/api/approvals/${approvalId}`, {
    method: "PATCH",
    body,
  });
}

type RunApprovalsParams = {
  mock_llm?: boolean;
  threshold?: number;
  send?: boolean;
};

type RunApprovalsResult = {
  feature: string;
  model: string;
  approval_request_count: number;
  notification_count: number;
  approval_requests: ApprovalRequest[];
};

export function runApprovalsPipeline(params: RunApprovalsParams = {}) {
  return apiFetch<RunApprovalsResult>("/api/approvals/run", {
    method: "POST",
    params: {
      mock_llm: params.mock_llm ?? mockLlm,
      send: params.send ?? false,
      threshold: params.threshold,
    },
  });
}
