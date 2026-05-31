"use client";

import { ASSISTANT_STARTER_PROMPTS } from "@/lib/assistant/starter-prompts";
import { cn } from "@/lib/utils";

type AssistantStarterGridProps = {
  selected: string | null;
  onSelect: (prompt: string | null) => void;
  disabled?: boolean;
};

export function AssistantStarterGrid({
  selected,
  onSelect,
  disabled,
}: AssistantStarterGridProps) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {ASSISTANT_STARTER_PROMPTS.map((starter) => {
        const isSelected = selected === starter.prompt;
        return (
          <button
            key={starter.prompt}
            type="button"
            disabled={disabled}
            onClick={() =>
              onSelect(isSelected ? null : starter.prompt)
            }
            className={cn(
              "rounded-[18px] border px-4 py-3 text-left transition-all shadow-[rgba(0,0,0,0.05)_0px_3px_0px_0px]",
              "border-dim-gray/40 bg-card hover:bg-blue-soft/40 hover:border-primary/30 hover:shadow-[rgba(154,207,246,0.4)_0px_5px_0px_0px] disabled:opacity-50",
              isSelected &&
                "border-primary/40 bg-blue-soft shadow-[rgba(154,207,246,0.5)_0px_5px_0px_0px]"
            )}
          >
            <p className="text-xs text-muted-foreground tracking-[-0.22px]">{starter.category}</p>
            <p className="mt-1 text-sm font-medium text-deep-ocean tracking-[-0.25px]">
              {starter.title}
            </p>
          </button>
        );
      })}
    </div>
  );
}
