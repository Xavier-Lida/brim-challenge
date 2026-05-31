"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { EmployeeRosterEntry } from "@/lib/types/brim";
import { cn } from "@/lib/utils";

type EmployeeMapFilterProps = {
  employees: EmployeeRosterEntry[];
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
};

function isSelectable(emp: EmployeeRosterEntry) {
  return emp.map_transaction_count > 0;
}

function countLabel(emp: EmployeeRosterEntry) {
  if (emp.map_transaction_count === 0) {
    return "No geo purchases";
  }
  const n = emp.map_transaction_count;
  return `${n} geo purchase${n !== 1 ? "s" : ""}`;
}

export function EmployeeMapFilter({
  employees,
  selectedIds,
  onSelectionChange,
}: EmployeeMapFilterProps) {
  const selectable = employees.filter(isSelectable);
  const selectableIds = selectable.map((e) => e.id);

  const toggle = (id: string) => {
    const emp = employees.find((e) => e.id === id);
    if (!emp || !isSelectable(emp)) return;
    const next = selectedIds.includes(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id];
    onSelectionChange(next);
  };

  const selectAll = () => onSelectionChange(selectableIds);
  const clearAll = () => onSelectionChange([]);

  const allSelectableSelected =
    selectableIds.length > 0 &&
    selectableIds.every((id) => selectedIds.includes(id));

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" size="sm" variant="outline" className="border-border/60">
          Employees
          {selectedIds.length > 0 && (
            <Badge variant="secondary" className="ml-2 font-normal">
              {selectedIds.length}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-72 w-64 overflow-y-auto">
        <TooltipProvider delayDuration={200}>
          <DropdownMenuGroup>
            <DropdownMenuLabel>Show on map</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem
              checked={allSelectableSelected}
              onCheckedChange={() =>
                allSelectableSelected ? clearAll() : selectAll()
              }
              disabled={selectable.length === 0}
            >
              Select all with geo purchases
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={selectedIds.length === 0}
              onCheckedChange={() => clearAll()}
            >
              Clear selection
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            {employees.map((emp) => {
              const disabled = !isSelectable(emp);
              const item = (
                <DropdownMenuCheckboxItem
                  key={emp.id}
                  checked={selectedIds.includes(emp.id)}
                  disabled={disabled}
                  onCheckedChange={() => toggle(emp.id)}
                  className={cn(disabled && "opacity-50")}
                >
                  <span className="flex flex-col gap-0.5">
                    <span>{emp.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {emp.department ? `${emp.department} · ` : ""}
                      {countLabel(emp)}
                    </span>
                  </span>
                </DropdownMenuCheckboxItem>
              );

              if (!disabled) return item;

              return (
                <Tooltip key={emp.id}>
                  <TooltipTrigger asChild>
                    <span className="block w-full">{item}</span>
                  </TooltipTrigger>
                  <TooltipContent side="right">
                    Aucun achat géolocalisé
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </DropdownMenuGroup>
        </TooltipProvider>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
