"use client";

import { useEffect, useRef } from "react";
import { AssistantVisualization } from "@/components/assistant/assistant-visualization";
import { AssistantStarterGrid } from "@/components/assistant/assistant-starter-grid";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { VisualizationHistoryEntry } from "@/lib/types/brim";
import { cn } from "@/lib/utils";

type AssistantCenterStageProps = {
  layoutMode: "centered" | "split";
  visualizationHistory: VisualizationHistoryEntry[];
  activeVisualizationId?: string;
  scrollToMessageId?: string;
  showStarters: boolean;
  selectedStarter: string | null;
  onStarterSelect: (prompt: string | null) => void;
  startersDisabled?: boolean;
  className?: string;
};

export function AssistantCenterStage({
  layoutMode,
  visualizationHistory,
  activeVisualizationId,
  scrollToMessageId,
  showStarters,
  selectedStarter,
  onStarterSelect,
  startersDisabled,
  className,
}: AssistantCenterStageProps) {
  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const prevHistoryLength = useRef(visualizationHistory.length);

  useEffect(() => {
    const targetId =
      scrollToMessageId ??
      (visualizationHistory.length > prevHistoryLength.current
        ? visualizationHistory.at(-1)?.messageId
        : undefined);
    prevHistoryLength.current = visualizationHistory.length;

    if (!targetId) return;
    const el = itemRefs.current.get(targetId);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [visualizationHistory.length, scrollToMessageId, visualizationHistory]);

  if (layoutMode === "centered") {
    if (!showStarters) return null;
    return (
      <div className={cn("flex w-full max-w-2xl flex-col gap-4 px-2", className)}>
        <div className="text-center">
          <h2 className="text-xl font-normal text-foreground/90">
            Brim Assistant
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Ask about spend, compliance, and policy coverage across Northwind
            Labs.
          </p>
        </div>
        <AssistantStarterGrid
          selected={selectedStarter}
          onSelect={onStarterSelect}
          disabled={startersDisabled}
        />
      </div>
    );
  }

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col p-4 md:p-8", className)}>
      {visualizationHistory.length === 0 ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-muted-foreground">
            Ask a question to generate a chart or report.
          </p>
        </div>
      ) : (
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex w-full max-w-4xl flex-col gap-6 pb-4">
            {visualizationHistory.map((entry) => {
              const isActive = entry.messageId === activeVisualizationId;
              return (
                <div
                  key={entry.messageId}
                  id={`viz-${entry.messageId}`}
                  ref={(node) => {
                    if (node) itemRefs.current.set(entry.messageId, node);
                    else itemRefs.current.delete(entry.messageId);
                  }}
                  className={cn(
                    "scroll-mt-4 rounded-xl transition-shadow",
                    isActive && "ring-1 ring-primary/30"
                  )}
                >
                  <AssistantVisualization
                    visualization={entry.visualization}
                    size="stage"
                  />
                </div>
              );
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
