"use client";

import { ArrowsOutIcon, PlusIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { AssistantLayoutMode } from "@/lib/types/brim";

type AssistantToolbarProps = {
  layoutMode: AssistantLayoutMode;
  onNewChat: () => void;
  onExpandViz?: () => void;
  canExpandViz?: boolean;
};

export function AssistantToolbar({
  layoutMode,
  onNewChat,
  onExpandViz,
  canExpandViz,
}: AssistantToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border/60 pb-3">
      <div className="ml-auto flex items-center gap-2">
        {layoutMode === "split" && canExpandViz && onExpandViz && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="border-border/60"
            onClick={onExpandViz}
          >
            <ArrowsOutIcon data-icon="inline-start" />
            Expand
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-border/60"
          onClick={onNewChat}
        >
          <PlusIcon data-icon="inline-start" />
          New chat
        </Button>
      </div>
    </div>
  );
}
