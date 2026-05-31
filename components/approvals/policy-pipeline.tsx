"use client";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { PolicyCheck } from "@/lib/types/brim";

type PolicyPipelineProps = {
  checks: PolicyCheck[];
};

function shortLabel(name: string, max = 8): string {
  if (name.length <= max) return name;
  return `${name.slice(0, max - 1)}…`;
}

function nodeColor(status: PolicyCheck["status"]): string {
  return status === "passed" ? "bg-emerald-500" : "bg-destructive";
}

export function PolicyPipeline({ checks }: PolicyPipelineProps) {
  if (checks.length === 0) return null;

  return (
    <TooltipProvider>
      <div className="overflow-x-auto pb-1">
        <div className="flex min-w-max items-start px-1">
          {checks.map((check, index) => {
            const isLast = index === checks.length - 1;
            const color = nodeColor(check.status);

            return (
              <div
                key={check.policy_id}
                className={cn("flex items-center", !isLast && "flex-1")}
              >
                <div className="flex shrink-0 flex-col items-center gap-1.5">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className="flex size-3.5 shrink-0 items-center justify-center rounded-full ring-2 ring-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label={`${check.policy_name}: ${check.status}`}
                      >
                        <span className={cn("size-full rounded-full", color)} />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p className="font-medium">{check.policy_name}</p>
                      <p className="capitalize text-background/80">
                        {check.status}
                      </p>
                      {check.message && (
                        <p className="mt-0.5 text-background/70">{check.message}</p>
                      )}
                    </TooltipContent>
                  </Tooltip>
                  <span className="max-w-14 truncate text-center text-[10px] leading-tight text-muted-foreground">
                    {shortLabel(check.policy_name)}
                  </span>
                </div>
                {!isLast && (
                  <div
                    className={cn("mx-1 mb-4 h-px min-w-6 flex-1", color)}
                    aria-hidden
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </TooltipProvider>
  );
}
