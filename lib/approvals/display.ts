import type {
  AiRecommendation,
  ApprovalRequest,
  ApprovalStatus,
  PolicyCheck,
  PolicyCheckStatus,
} from "@/lib/types/brim";

export function normalizePolicyCheckStatus(raw: unknown): PolicyCheckStatus {
  const v = String(raw ?? "")
    .toLowerCase()
    .trim();
  if (v === "passed" || v === "pass" || v === "ok" || v === "success") {
    return "passed";
  }
  return "failed";
}

export function normalizePolicyChecks(checks: PolicyCheck[]): PolicyCheck[] {
  return checks.map((check) => ({
    ...check,
    status: normalizePolicyCheckStatus(check.status),
  }));
}

export function normalizeApprovalStatus(raw: unknown): ApprovalStatus {
  const v = String(raw ?? "pending")
    .toLowerCase()
    .trim();
  if (v === "approved" || v === "approve") return "approved";
  if (v === "denied" || v === "deny" || v === "rejected") return "denied";
  return "pending";
}

export function normalizeAiRecommendation(raw: unknown): AiRecommendation {
  const v = String(raw ?? "review")
    .toLowerCase()
    .trim();
  if (v === "approve" || v === "approved") return "approve";
  if (v === "deny" || v === "denied") return "deny";
  return "review";
}

export function normalizeApprovalRequest(item: ApprovalRequest): ApprovalRequest {
  const record = item as ApprovalRequest & {
    approval_status?: unknown;
    ai_recommendation?: unknown;
  };

  return {
    ...item,
    employee_name: String(item.employee_name ?? "").trim(),
    department_name: String(item.department_name ?? "").trim(),
    reason: String(item.reason ?? "").trim(),
    ai_reasoning: String(item.ai_reasoning ?? "").trim(),
    status: normalizeApprovalStatus(record.approval_status ?? item.status),
    ai_recommendation: normalizeAiRecommendation(item.ai_recommendation),
    policy_checks: item.policy_checks?.length
      ? normalizePolicyChecks(item.policy_checks)
      : item.policy_checks,
    policy_violation_summary:
      typeof item.policy_violation_summary === "string"
        ? item.policy_violation_summary.trim()
        : item.policy_violation_summary,
  };
}

const CAD_FORMATTER = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
});

export function formatCad(value: number): string {
  return CAD_FORMATTER.format(value);
}

export function getFailedPolicyChecks(checks: PolicyCheck[]): PolicyCheck[] {
  return checks.filter((c) => c.status === "failed");
}

const TECHNICAL_PATTERNS = [
  /status\s*=\s*['"]/i,
  /at\/above/i,
  /pre-approval threshold/i,
  /is not marked approved/i,
  /threshold and is not/i,
];

export function isTechnicalApprovalText(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  return TECHNICAL_PATTERNS.some((pattern) => pattern.test(trimmed));
}

export function humanizeApprovalText(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;

  let result = trimmed
    .replace(/\s*\(status\s*=\s*['"][^'"]+['"]\)\.?/gi, "")
    .replace(/\s*status\s*=\s*['"][^'"]+['"]\.?/gi, "")
    .trim();

  const thresholdMatch = result.match(
    /\$?([\d,]+(?:\.\d+)?)\s*is at\/above the \$?([\d,]+(?:\.\d+)?)\s*(?:CAD\s*)?pre-approval threshold/i
  );
  if (thresholdMatch) {
    const amount = thresholdMatch[1];
    const threshold = thresholdMatch[2];
    return `Exceeds the $${threshold} pre-approval threshold ($${amount}) — manager approval required.`;
  }

  const exceedsMatch = result.match(
    /(?:amount\s*)?\$?([\d,]+(?:\.\d+)?)\s*exceeds\s*\$?([\d,]+(?:\.\d+)?)/i
  );
  if (exceedsMatch) {
    return `Exceeds the $${exceedsMatch[2]} limit ($${exceedsMatch[1]}).`;
  }

  if (result.endsWith(".")) return result;
  return `${result}.`;
}

const AI_FALLBACK: Record<AiRecommendation, string> = {
  approve: "Within policy — ready to approve.",
  review: "Needs review — check policy details before deciding.",
  deny: "Policy concerns — review before approving.",
};

export function getApprovalPolicySummary(
  approval: ApprovalRequest,
  checks: PolicyCheck[]
): {
  failedCount: number;
  passedCount: number;
  topFailure?: string;
} {
  const failed = checks.filter((c) => c.status === "failed");
  const passed = checks.filter((c) => c.status === "passed");
  const topFailure = failed[0]?.policy_name;

  return {
    failedCount: failed.length,
    passedCount: passed.length,
    topFailure,
  };
}

export function getApprovalCardSummary(
  approval: ApprovalRequest,
  checks: PolicyCheck[] = []
): {
  headline: string;
  subtitle?: string;
} {
  const failedCheck = checks.find((c) => c.status === "failed");
  const reason = approval.reason.trim();
  const aiReasoning = approval.ai_reasoning.trim();

  let headline: string;

  if (reason && !isTechnicalApprovalText(reason)) {
    headline = reason;
  } else if (failedCheck?.message) {
    headline = humanizeApprovalText(failedCheck.message);
  } else if (aiReasoning) {
    headline = isTechnicalApprovalText(aiReasoning)
      ? humanizeApprovalText(aiReasoning)
      : aiReasoning;
  } else if (reason) {
    headline = humanizeApprovalText(reason);
  } else {
    headline = AI_FALLBACK[approval.ai_recommendation];
  }

  const recent = approval.recent_expenses[0];
  const subtitle = recent
    ? `${recent.merchant} · ${recent.date}`
    : undefined;

  return { headline, subtitle };
}

export function getApprovalReasonDisplay(
  approval: ApprovalRequest,
  checks: PolicyCheck[] = []
): {
  label: string;
  text: string;
} {
  const reason = approval.reason.trim();

  if (reason && !isTechnicalApprovalText(reason)) {
    return { label: "Reason", text: reason };
  }

  const failedMessage = checks.find((c) => c.status === "failed")?.message;
  if (failedMessage) {
    return {
      label: "Policy evaluation",
      text: humanizeApprovalText(failedMessage),
    };
  }

  if (reason) {
    return {
      label: "Policy evaluation",
      text: humanizeApprovalText(reason),
    };
  }

  return {
    label: "Policy evaluation",
    text: AI_FALLBACK[approval.ai_recommendation],
  };
}
