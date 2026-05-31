import type { ApprovalRequest } from "@/lib/types/brim";

function sortApprovals(items: ApprovalRequest[]): ApprovalRequest[] {
  return [...items].sort((a, b) => {
    const aPending = a.status === "pending" ? 0 : 1;
    const bPending = b.status === "pending" ? 0 : 1;
    return aPending - bPending;
  });
}

export function matchesEmployeeQuery(
  approval: ApprovalRequest,
  employeeQuery: string
): boolean {
  const q = employeeQuery.toLowerCase().trim();
  if (!q) return true;
  return (
    approval.employee_name.toLowerCase().includes(q) ||
    approval.department_name.toLowerCase().includes(q)
  );
}

export function filterApprovals(
  items: ApprovalRequest[],
  employeeQuery = ""
): ApprovalRequest[] {
  const filtered = items.filter((item) =>
    matchesEmployeeQuery(item, employeeQuery)
  );

  if (!employeeQuery.trim()) {
    return sortApprovals(filtered);
  }

  return filtered;
}
