"use client";

import { Progress } from "@/components/ui/progress";
import { useMockStore } from "@/lib/hooks/use-mock-store";

export function CompanySpendCard() {
  const { companySpend } = useMockStore();
  const pct = Math.round((companySpend.spent / companySpend.budget) * 100);
  const spentLabel = `$${(companySpend.spent / 1000).toFixed(1)}k`;
  const budgetLabel = `$${(companySpend.budget / 1000).toFixed(0)}k`;

  return (
    <div className="rounded-[14px] border border-sidebar-border bg-white/10 p-3">
      <p className="text-xs text-sidebar-foreground/60">
        Company spend · {companySpend.period}
      </p>
      <p className="mt-1 text-sm font-semibold text-sidebar-foreground tracking-[-0.25px]">
        {spentLabel}{" "}
        <span className="font-normal text-sidebar-foreground/60">/ {budgetLabel}</span>
      </p>
      <Progress value={pct} className="mt-2 h-1.5 bg-white/20 [&>[data-slot=progress-indicator]]:bg-hope-blue" />
    </div>
  );
}
