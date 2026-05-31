"use client";

import { PolicyPipeline } from "@/components/approvals/policy-pipeline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { getApprovalReasonDisplay } from "@/lib/approvals/display";
import { resolvePolicyChecks } from "@/lib/approvals/policy-checks";
import type { AiRecommendation, ApprovalRequest } from "@/lib/types/brim";

const recommendationVariant: Record<
  AiRecommendation,
  "default" | "secondary" | "destructive"
> = {
  approve: "default",
  review: "secondary",
  deny: "destructive",
};

type ApprovalInspectSheetProps = {
  approval: ApprovalRequest | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDecide: (id: string, status: "approved" | "denied") => void | Promise<void>;
  isSubmitting?: boolean;
};

export function ApprovalInspectSheet({
  approval,
  open,
  onOpenChange,
  onDecide,
  isSubmitting = false,
}: ApprovalInspectSheetProps) {
  if (!approval) return null;

  const isPending = approval.status === "pending";
  const policyChecks = resolvePolicyChecks(approval);
  const reasonDisplay = getApprovalReasonDisplay(approval, policyChecks);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <div className="flex flex-wrap items-center gap-2 pr-8">
            <SheetTitle className="text-base">{approval.employee_name}</SheetTitle>
            <Badge
              variant={
                approval.ai_recommendation === "approve"
                  ? "secondary"
                  : recommendationVariant[approval.ai_recommendation]
              }
              className={
                approval.ai_recommendation === "approve"
                  ? "border border-primary/20 bg-blue-soft text-primary/80"
                  : undefined
              }
            >
              AI: {approval.ai_recommendation}
            </Badge>
            <Badge variant="secondary">{approval.status}</Badge>
          </div>
          <SheetDescription>
            {approval.department_name} · ${approval.amount.toFixed(2)}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-4 px-4 pb-4">
          {policyChecks.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-xs font-medium text-muted-foreground">
                Policy checks
              </p>
              <PolicyPipeline checks={policyChecks} />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">
              {reasonDisplay.label}
            </p>
            <p className="text-sm text-foreground">{reasonDisplay.text}</p>
          </div>

          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">
              AI reasoning
            </p>
            <div className="rounded-md bg-muted/40 px-3 py-2">
              <p className="text-xs leading-relaxed text-muted-foreground">
                {approval.ai_reasoning}
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            <p>
              Budget remaining: $
              {approval.department_budget_remaining.toLocaleString()}
            </p>
            {approval.recent_expenses.length > 0 && (
              <div className="flex flex-col gap-1">
                <p className="font-medium">Recent expenses</p>
                <ul className="flex flex-col gap-0.5">
                  {approval.recent_expenses.map((exp, i) => (
                    <li key={i}>
                      {exp.date} · {exp.merchant} · ${exp.amount.toFixed(2)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        {isPending && (
          <SheetFooter className="flex-row gap-2 border-t border-border/60 pt-4">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => void onDecide(approval.id, "denied")}
              disabled={isSubmitting}
            >
              Deny
            </Button>
            <Button
              className="flex-1"
              onClick={() => void onDecide(approval.id, "approved")}
              disabled={isSubmitting}
            >
              {isSubmitting ? "Saving…" : "Approve"}
            </Button>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}
