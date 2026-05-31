import { normalizePolicyChecks } from "@/lib/approvals/display";
import { initialApprovals } from "@/lib/mocks/fixtures";
import type { ApprovalRequest, PolicyCheck } from "@/lib/types/brim";

const fallbackByApprovalId = new Map<string, PolicyCheck[]>(
  initialApprovals
    .filter((a) => a.policy_checks?.length)
    .map((a) => [a.id, normalizePolicyChecks(a.policy_checks!)])
);

export function resolvePolicyChecks(approval: ApprovalRequest): PolicyCheck[] {
  if (approval.policy_checks?.length) {
    return normalizePolicyChecks(approval.policy_checks);
  }
  return fallbackByApprovalId.get(approval.id) ?? [];
}
