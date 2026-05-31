"use client";

import type { EmployeeRosterEntry } from "@/lib/types/brim";
import { getEmployeeColor } from "@/lib/map/colors";

type MapLegendProps = {
  employees: EmployeeRosterEntry[];
  selectedIds: string[];
  colorIndex: Map<string, number>;
};

export function MapLegend({ employees, selectedIds, colorIndex }: MapLegendProps) {
  const items = employees.filter((e) => selectedIds.includes(e.id));
  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-3 px-1 pt-2">
      {items.map((emp) => {
        const idx = colorIndex.get(emp.id) ?? 0;
        const color = getEmployeeColor(idx);
        return (
          <div key={emp.id} className="flex items-center gap-2 text-sm">
            <span
              className="size-3 shrink-0 rounded-full ring-1 ring-border/60"
              style={{ backgroundColor: color }}
              aria-hidden
            />
            <span className="text-foreground/90">{emp.name}</span>
          </div>
        );
      })}
    </div>
  );
}
