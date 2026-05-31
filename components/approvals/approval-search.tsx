"use client";

import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { Input } from "@/components/ui/input";

type ApprovalSearchProps = {
  value: string;
  onChange: (value: string) => void;
};

export function ApprovalSearch({ value, onChange }: ApprovalSearchProps) {
  return (
    <div className="relative">
      <MagnifyingGlassIcon className="absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
      <Input
        placeholder="Search by employee name…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border-border/60 bg-muted/50 pl-8"
      />
    </div>
  );
}
