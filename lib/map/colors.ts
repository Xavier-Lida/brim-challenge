export const EMPLOYEE_MAP_COLORS = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#ca8a04",
  "#9333ea",
  "#0891b2",
  "#ea580c",
  "#db2777",
  "#4f46e5",
  "#0d9488",
] as const;

export function getEmployeeColor(employeeIndex: number): string {
  return EMPLOYEE_MAP_COLORS[employeeIndex % EMPLOYEE_MAP_COLORS.length];
}

export function buildEmployeeColorIndex(
  employees: { id: string }[]
): Map<string, number> {
  const sorted = [...employees].sort((a, b) => a.id.localeCompare(b.id));
  const index = new Map<string, number>();
  sorted.forEach((emp, i) => index.set(emp.id, i));
  return index;
}
