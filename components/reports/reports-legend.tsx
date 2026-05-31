"use client";

import { Badge } from "@/components/ui/badge";
import {
  REPORT_AI_META,
  REPORT_STATUS_META,
  type ReportStatus,
} from "@/lib/reports/display";
import type { AiRecommendation } from "@/lib/types/brim";
import { cn } from "@/lib/utils";

const STATUS_ORDER: ReportStatus[] = [
  "draft",
  "ready_for_approval",
  "approved",
  "rejected",
];

const AI_ORDER: AiRecommendation[] = ["approve", "review", "deny"];

export function ReportsLegend() {
  return (
    <div className="grid gap-4 rounded-none border border-border/50 bg-muted/20 p-4 sm:grid-cols-2">
      <div>
        <p className="text-xs font-medium text-foreground/80">
          AI recommendation
        </p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {AI_ORDER.map((key) => {
            const meta = REPORT_AI_META[key];
            return (
              <li key={key} className="flex gap-2 text-xs text-muted-foreground">
                <Badge
                  variant={key === "deny" ? "destructive" : "secondary"}
                  className={cn(
                    "shrink-0",
                    key === "approve" &&
                      "border border-primary/20 bg-blue-soft text-primary/80"
                  )}
                >
                  AI: {meta.label}
                </Badge>
                <span>{meta.description}</span>
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <p className="text-xs font-medium text-foreground/80">Report status</p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {STATUS_ORDER.map((key) => {
            const meta = REPORT_STATUS_META[key];
            return (
              <li key={key} className="flex gap-2 text-xs text-muted-foreground">
                <Badge variant={meta.badgeVariant} className="shrink-0">
                  {meta.label}
                </Badge>
                <span>{meta.description}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
