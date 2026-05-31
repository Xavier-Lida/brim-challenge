"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AssistantVisualization } from "@/components/assistant/assistant-visualization";
import type { Visualization } from "@/lib/types/brim";

type VizFullscreenDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  visualization?: Visualization;
};

export function VizFullscreenDialog({
  open,
  onOpenChange,
  visualization,
}: VizFullscreenDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-none flex-col gap-3 overflow-hidden p-4 sm:max-w-none">
        <DialogHeader className="shrink-0">
          <DialogTitle className="font-normal">
            {visualization?.title ?? "Visualization"}
          </DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col">
          {visualization && (
            <AssistantVisualization
              visualization={visualization}
              size="fullscreen"
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
