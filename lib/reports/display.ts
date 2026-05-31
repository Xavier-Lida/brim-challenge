import type { AiRecommendation } from "@/lib/types/brim";

export type ReportStatus =
  | "draft"
  | "ready_for_approval"
  | "approved"
  | "rejected"
  | "processing";

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

export type ReportStatusMeta = {
  label: string;
  badgeVariant: BadgeVariant;
  description: string;
};

export type ReportAiMeta = {
  label: string;
  action: string;
  description: string;
};

/** Tolerant of the various status strings the backend may emit. */
export function normalizeReportStatus(raw: unknown): ReportStatus {
  const v = String(raw ?? "")
    .toLowerCase()
    .trim()
    .replace(/[\s-]+/g, "_");

  if (
    v === "ready_for_approval" ||
    v === "ready" ||
    v === "submitted" ||
    v === "pending_approval" ||
    v === "awaiting_approval"
  ) {
    return "ready_for_approval";
  }
  if (v === "approved" || v === "approve") return "approved";
  if (v === "rejected" || v === "denied" || v === "deny" || v === "declined") {
    return "rejected";
  }
  if (v === "processing" || v === "generating" || v === "in_progress") {
    return "processing";
  }
  return "draft";
}

export const REPORT_STATUS_META: Record<ReportStatus, ReportStatusMeta> = {
  draft: {
    label: "Draft",
    badgeVariant: "outline",
    description:
      "Still being assembled from transactions. Not ready for a decision yet.",
  },
  processing: {
    label: "Processing",
    badgeVariant: "outline",
    description:
      "The AI is still reviewing this report. Check back in a moment.",
  },
  ready_for_approval: {
    label: "Ready for approval",
    badgeVariant: "default",
    description:
      "Reviewed by the AI and waiting for a manager to sign off, request changes, or reject it.",
  },
  approved: {
    label: "Approved",
    badgeVariant: "secondary",
    description: "A manager has approved this report. No further action needed.",
  },
  rejected: {
    label: "Rejected",
    badgeVariant: "destructive",
    description:
      "This report was rejected and sent back. The employee needs to address the issues.",
  },
};

export const REPORT_AI_META: Record<AiRecommendation, ReportAiMeta> = {
  approve: {
    label: "Safe to approve",
    action: "You can approve with confidence.",
    description:
      "The AI found no policy issues or risky spend. It is safe to approve as-is.",
  },
  review: {
    label: "Needs a quick review",
    action: "Take a closer look before deciding.",
    description:
      "The AI flagged something worth a second look — an unusual amount, category, or merchant — before you approve.",
  },
  deny: {
    label: "Recommend rejecting",
    action: "Likely should be rejected.",
    description:
      "The AI found policy concerns serious enough that it recommends rejecting this report.",
  },
};

export function getReportStatusMeta(raw: unknown): ReportStatusMeta {
  return REPORT_STATUS_META[normalizeReportStatus(raw)];
}

const CURRENCY_FORMATTERS = new Map<string, Intl.NumberFormat>();

/** Format a report total, honoring the backend-provided currency (defaults to CAD). */
export function formatReportAmount(amount: number, currency?: string): string {
  const code = (currency ?? "CAD").toUpperCase();
  let formatter = CURRENCY_FORMATTERS.get(code);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-CA", {
      style: "currency",
      currency: code,
    });
    CURRENCY_FORMATTERS.set(code, formatter);
  }
  return formatter.format(amount);
}
