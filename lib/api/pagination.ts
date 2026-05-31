import type {
  ApprovalRequest,
  ApprovalsPage,
  ExpenseReport,
  FlagsPage,
  ReportsPage,
  TransactionFlag,
} from "@/lib/types/brim";
import { normalizeApprovalRequest } from "@/lib/approvals/display";

function normalizeApprovalItems(items: ApprovalRequest[]): ApprovalRequest[] {
  return items.map(normalizeApprovalRequest);
}

function sortApprovals(all: ApprovalRequest[]): ApprovalRequest[] {
  return [...all].sort((a, b) => {
    const aPending = a.status === "pending" ? 0 : 1;
    const bPending = b.status === "pending" ? 0 : 1;
    return aPending - bPending;
  });
}

/** Normalize legacy array responses until backend returns paginated JSON. */
export function normalizeApprovalsPage(
  data: unknown,
  limit: number,
  offset: number
): ApprovalsPage {
  if (Array.isArray(data)) {
    const sorted = sortApprovals(normalizeApprovalItems(data as ApprovalRequest[]));
    const pending_count = sorted.filter((a) => a.status === "pending").length;
    const items = sorted.slice(offset, offset + limit);
    return {
      items,
      has_more: offset + items.length < sorted.length,
      limit,
      offset,
      pending_count,
    };
  }
  const page = data as ApprovalsPage;
  const items = normalizeApprovalItems(page.items ?? []);
  return {
    items,
    has_more: Boolean(page.has_more),
    limit: page.limit ?? limit,
    offset: page.offset ?? offset,
    pending_count:
      typeof page.pending_count === "number"
        ? page.pending_count
        : items.filter((a) => a.status === "pending").length,
  };
}

/** Normalize legacy array responses until backend returns paginated JSON. */
export function normalizeFlagsPage(
  data: unknown,
  limit: number,
  offset: number
): FlagsPage {
  if (Array.isArray(data)) {
    const all = data as TransactionFlag[];
    const sorted = [...all].sort((a, b) => b.weight - a.weight);
    const unread_count = sorted.filter((f) => !f.reviewed).length;
    const items = sorted.slice(offset, offset + limit);
    return {
      items,
      has_more: offset + items.length < sorted.length,
      limit,
      offset,
      unread_count,
    };
  }
  const page = data as FlagsPage;
  return {
    items: page.items ?? [],
    has_more: Boolean(page.has_more),
    limit: page.limit ?? limit,
    offset: page.offset ?? offset,
    unread_count:
      typeof page.unread_count === "number"
        ? page.unread_count
        : (page.items ?? []).filter((f) => !f.reviewed).length,
  };
}

export function normalizeReportsPage(
  data: unknown,
  limit: number,
  offset: number
): ReportsPage {
  if (Array.isArray(data)) {
    const all = data as ExpenseReport[];
    const items = all.slice(offset, offset + limit);
    return {
      items,
      has_more: offset + items.length < all.length,
      limit,
      offset,
      total_count: all.length,
    };
  }
  const page = data as ReportsPage;
  return {
    items: page.items ?? [],
    has_more: Boolean(page.has_more),
    limit: page.limit ?? limit,
    offset: page.offset ?? offset,
    total_count:
      typeof page.total_count === "number"
        ? page.total_count
        : (page.items ?? []).length,
  };
}
