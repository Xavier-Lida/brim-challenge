"use client";

import { CaretDownIcon } from "@phosphor-icons/react";
import { PolicyPipeline } from "@/components/approvals/policy-pipeline";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  formatCad,
  getFailedPolicyChecks,
} from "@/lib/approvals/display";
import { resolvePolicyChecks } from "@/lib/approvals/policy-checks";
import { useApprovalQueue } from "@/lib/approvals/use-approval-queue";
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

type ApprovalDeckProps = {
  approvals: ApprovalRequest[];
  onDecide: (id: string, status: "approved" | "denied") => void | Promise<void>;
  isSubmitting?: boolean;
};

export function ApprovalDeck({
  approvals,
  onDecide,
  isSubmitting = false,
}: ApprovalDeckProps) {
  const {
    current,
    queueSize,
    position,
    skip,
    removeCurrent,
    expanded,
    setExpanded,
  } = useApprovalQueue(approvals);

  const handleDecide = async (status: "approved" | "denied") => {
    if (!current) return;
    await onDecide(current.id, status);
    removeCurrent();
  };

  if (!current) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 bg-card/50 px-6 py-16 text-center">
        <p className="text-lg font-medium text-foreground/90">All caught up</p>
        <p className="mt-1 text-sm text-muted-foreground">
          No pending approvals in your queue.
        </p>
      </div>
    );
  }

  const policyChecks = resolvePolicyChecks(current);
  const failedChecks = getFailedPolicyChecks(policyChecks);
  const triggeringFlags = current.flags ?? [];
  const pill = recommendationPill[current.ai_recommendation];
  const reason = current.reason.trim();
  const summary = current.policy_violation_summary?.trim();
  const merchant = current.merchant_name?.trim() || "Unknown merchant";
  const date = current.transaction_date?.trim() || "—";
  const category = current.merchant_category?.trim() || "—";
  const city = current.city?.trim();

  return (
    <div className="flex flex-col gap-4">
      <p className="text-center text-sm text-muted-foreground">
        {position} of {queueSize} pending
      </p>

      <Card className="mx-auto w-full max-w-lg rounded-xl border-border/50 shadow-none transition-opacity duration-200">
        <CardHeader className="gap-3 pb-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <CardTitle className="text-lg font-medium">
                {current.employee_name}
              </CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {current.department_name}
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

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <Detail label="Amount" value={formatCad(current.amount)} />
            <Detail label="Date" value={date} />
            <Detail label="Merchant" value={merchant} className="col-span-2" />
            <Detail label="Category" value={category} />
            {city ? <Detail label="City" value={city} /> : null}
          </dl>

          {reason && (
            <p className="text-sm font-medium text-foreground">{reason}</p>
          )}
        </CardHeader>

        <CardContent className="flex flex-col gap-3 pt-0">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
            aria-expanded={expanded}
          >
            <CaretDownIcon
              className={cn(
                "size-4 transition-transform",
                expanded && "rotate-180"
              )}
            />
            {expanded ? "Hide details" : "Show details"}
          </button>

          {expanded && (
            <div className="flex flex-col gap-3 border-t border-border/50 pt-3">
              <p className="text-sm leading-relaxed text-muted-foreground">
                {current.ai_reasoning}
              </p>

              {triggeringFlags.length > 0 && (
                <div className="flex flex-col gap-2">
                  <p className="text-xs font-medium text-foreground/80">
                    Triggering flags
                  </p>
                  <ul className="flex flex-col gap-1.5">
                    {triggeringFlags.map((flag, i) => (
                      <li
                        key={flag.incident_id ?? `${flag.policy_id ?? "flag"}-${i}`}
                        className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2"
                      >
                        <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                          <span className="inline-block size-1.5 rounded-full bg-amber-500" />
                          {flag.policy_name ?? "Compliance flag"}
                          <span className="ml-auto tabular-nums text-muted-foreground">
                            {flag.weight}/5
                          </span>
                        </p>
                        {flag.warning_message && (
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {flag.warning_message}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
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

              <PolicyPipeline checks={policyChecks} />

              <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                <p>
                  Budget remaining:{" "}
                  {formatCad(current.department_budget_remaining)}
                </p>
                {current.recent_expenses.length > 0 && (
                  <div className="flex flex-col gap-0.5">
                    <p className="font-medium text-foreground/70">
                      Recent expenses
                    </p>
                    <ul className="flex flex-col gap-0.5">
                      {current.recent_expenses.slice(0, 3).map((exp, i) => (
                        <li key={i}>
                          {exp.date} · {exp.merchant} · {formatCad(exp.amount)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>

        <CardFooter className="flex flex-wrap gap-2 pt-2">
          <Button
            variant="outline"
            className="flex-1 min-w-[5rem] border-destructive/40 text-destructive hover:bg-destructive/10"
            onClick={() => void handleDecide("denied")}
            disabled={isSubmitting}
          >
            Deny
          </Button>
          <Button
            variant="secondary"
            className="flex-1 min-w-[5rem]"
            onClick={skip}
            disabled={isSubmitting || queueSize <= 1}
          >
            Skip
          </Button>
          <Button
            className="flex-1 min-w-[5rem]"
            onClick={() => void handleDecide("approved")}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Saving…" : "Approve"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

function Detail({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="text-[0.65rem] uppercase tracking-wide text-muted-foreground/70">
        {label}
      </dt>
      <dd className="mt-0.5 font-medium text-foreground">{value}</dd>
    </div>
  );
}
