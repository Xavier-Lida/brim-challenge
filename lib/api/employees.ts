import { apiFetch } from "@/lib/api/client";
import type { EmployeeRosterEntry } from "@/lib/types/brim";

/** Prefer this endpoint for any employee roster UI (name + department + geo purchase count). */
export function getEmployees() {
  return apiFetch<unknown>("/api/employees").then(normalizeEmployeeRoster);
}

function normalizeEmployeeRoster(data: unknown): EmployeeRosterEntry[] {
  if (!Array.isArray(data)) return [];

  return data.map((row) => {
    const r = row as Record<string, unknown>;
    const mapCount =
      typeof r.map_transaction_count === "number"
        ? r.map_transaction_count
        : typeof r.transaction_count === "number"
          ? r.transaction_count
          : 0;

    return {
      id: String(r.id ?? ""),
      name: String(r.name ?? ""),
      department: String(r.department ?? ""),
      map_transaction_count: mapCount,
    };
  });
}
