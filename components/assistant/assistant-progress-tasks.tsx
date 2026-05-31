"use client";

import { CheckIcon, CircleIcon } from "@phosphor-icons/react";
import type { AssistantProgressStep } from "@/lib/types/brim";
import { cn } from "@/lib/utils";

type AssistantProgressTasksProps = {
  steps: AssistantProgressStep[];
  activity?: string;
  compact?: boolean;
  className?: string;
};

export function AssistantProgressTasks({
  steps,
  activity,
  compact,
  className,
}: AssistantProgressTasksProps) {
  const doneCount = steps.filter((s) => s.status === "done").length;
  const progressPct = steps.length
    ? Math.round((doneCount / steps.length) * 100)
    : 0;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="h-1 w-full overflow-hidden rounded-full bg-border/50">
        <div
          className="h-full rounded-full bg-primary/70 transition-all duration-500 ease-out"
          style={{ width: `${progressPct}%` }}
        />
      </div>
      <ul className={cn("flex flex-col", compact ? "gap-1" : "gap-1.5")}>
        {steps.map((step) => (
          <li key={step.id} className="flex items-start gap-2 text-sm">
            <StepIcon status={step.status} />
            <span
              className={cn(
                "leading-snug transition-colors duration-300",
                step.status === "done" &&
                  "text-muted-foreground line-through decoration-muted-foreground/50",
                step.status === "active" && "font-medium text-foreground",
                step.status === "pending" && "text-muted-foreground/70"
              )}
            >
              {step.label}
            </span>
          </li>
        ))}
      </ul>
      {activity && (
        <p className="text-xs text-muted-foreground animate-pulse">{activity}</p>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: AssistantProgressStep["status"] }) {
  if (status === "done") {
    return (
      <CheckIcon
        weight="bold"
        className="mt-0.5 size-4 shrink-0 animate-in zoom-in-50 text-[var(--timeline-done)] duration-300"
      />
    );
  }
  if (status === "active") {
    return (
      <span className="relative mt-0.5 flex size-4 shrink-0 items-center justify-center">
        <CircleIcon
          weight="fill"
          className="size-3 animate-pulse text-primary"
        />
      </span>
    );
  }
  return (
    <CircleIcon
      weight="regular"
      className="mt-0.5 size-4 shrink-0 text-muted-foreground/40"
    />
  );
}
