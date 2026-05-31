"use client";

import type { FollowUpChoice } from "@/lib/assistant/follow-up-catalog";
import { cn } from "@/lib/utils";

type AssistantFollowUpChoicesProps = {
  choices: FollowUpChoice[];
  selected: string | null;
  onSelect: (choice: string | null) => void;
  disabled?: boolean;
  className?: string;
};

export function AssistantFollowUpChoices({
  choices,
  selected,
  onSelect,
  disabled,
  className,
}: AssistantFollowUpChoicesProps) {
  return (
    <div className={cn("flex flex-col gap-1 px-1 py-1.5", className)}>
      {choices.map((entry) => {
        const isSelected =
          selected === entry.prompt || selected === entry.chip;
        return (
          <button
            key={entry.id}
            type="button"
            disabled={disabled}
            title={entry.hint}
            onClick={() => onSelect(isSelected ? null : entry.prompt)}
            className={cn(
              "w-full truncate rounded-[10px] border px-3 py-1.5 text-left text-xs transition-all",
              "border-dim-gray/40 bg-card hover:bg-blue-soft/40 hover:border-primary/30",
              "disabled:pointer-events-none disabled:opacity-50",
              isSelected &&
                "border-primary/40 bg-blue-soft shadow-[rgba(154,207,246,0.4)_0px_3px_0px_0px]"
            )}
          >
            {entry.label}
          </button>
        );
      })}
    </div>
  );
}
