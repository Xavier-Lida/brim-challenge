"use client";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatCad, getFailedPolicyChecks } from "@/lib/approvals/display";
import { resolvePolicyChecks } from "@/lib/approvals/policy-checks";
import { cn } from "@/lib/utils";
import type { AiRecommendation, ApprovalRequest } from "@/lib/types/brim";

const recommendationPill: Record<
  AiRecommendation,
  { label: string; className: string }
> = {
  approve: {
    label: "AI: Approve",
    className:
      "border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  review: {
    label: "AI: Review",
    className:
      "border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  deny: {
    label: "AI: Deny",
    className:
      "border border-destructive/30 bg-destructive/10 text-destructive",
  },
};

type ApprovalCardProps = {
  approval: ApprovalRequest;
  onDecide: (id: string, status: "approved" | "denied") => void | Promise<void>;
  onInspect: () => void;
  isSubmitting?: boolean;
};

export function ApprovalCard({
  approval,
  onDecide,
  onInspect,
  isSubmitting = false,
}: ApprovalCardProps) {
  const isPending = approval.status === "pending";
  const policyChecks = resolvePolicyChecks(approval);
  const failedChecks = getFailedPolicyChecks(policyChecks);
  const pill = recommendationPill[approval.ai_recommendation];
  const reason = approval.reason.trim();
  const summary = approval.policy_violation_summary?.trim();

  return (
    <Card className="rounded-xl border-border/50 shadow-none">
      <CardHeader className="gap-3 pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base font-medium">
              {approval.employee_name}
            </CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {approval.department_name} · {formatCad(approval.amount)}
            </p>
          </div>
          <span
            className={cn(
              "shrink-0 rounded-full px-3 py-1 text-xs font-semibold",
              pill.className
            )}
          >
            {pill.label}
          </span>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {approval.ai_reasoning}
        </p>
      </CardHeader>

      <CardContent className="flex flex-col gap-3 pt-0">
        {reason && (
          <p className="text-sm font-medium text-foreground">{reason}</p>
        )}

        {summary && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {summary}
          </div>
        )}

        {failedChecks.length > 0 && (
          <ul className="flex flex-col gap-2">
            {failedChecks.map((check) => (
              <li
                key={check.policy_id}
                className="rounded-md border border-border/60 bg-muted/30 px-3 py-2"
              >
                <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                  <span className="inline-block size-1.5 rounded-full bg-destructive" />
                  {check.policy_name}
                </p>
                {check.message && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {check.message}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
          <p>
            Budget remaining: {formatCad(approval.department_budget_remaining)}
          </p>
          {approval.recent_expenses.length > 0 && (
            <div className="flex flex-col gap-0.5">
              <p className="font-medium text-foreground/70">Recent expenses</p>
              <ul className="flex flex-col gap-0.5">
                {approval.recent_expenses.slice(0, 3).map((exp, i) => (
                  <li key={i}>
                    {exp.date} · {exp.merchant} · {formatCad(exp.amount)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter className="gap-2 pt-0">
        <Button variant="ghost" size="sm" onClick={onInspect}>
          Inspect
        </Button>
        {isPending && (
          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              onClick={() => void onDecide(approval.id, "denied")}
              disabled={isSubmitting}
            >
              Deny
            </Button>
            <Button
              onClick={() => void onDecide(approval.id, "approved")}
              disabled={isSubmitting}
            >
              {isSubmitting ? "Saving…" : "Approve"}
            </Button>
          </div>
        )}
      </CardFooter>
    </Card>
  );
}
