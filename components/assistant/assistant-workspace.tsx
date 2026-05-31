"use client";

import { useState } from "react";
import { AssistantToolbar } from "@/components/assistant/assistant-toolbar";
import { AssistantCenterStage } from "@/components/assistant/assistant-center-stage";
import { AssistantChatPanel } from "@/components/assistant/assistant-chat-panel";
import { VizFullscreenDialog } from "@/components/assistant/viz-fullscreen-dialog";
import { useMockStore } from "@/lib/hooks/use-mock-store";
import { cn } from "@/lib/utils";

export function AssistantWorkspace() {
  const {
    assistantSession,
    assistantLatestVisualization,
    assistantVisualizationHistory,
    assistantIsSending,
    assistantVizFullscreenOpen,
    setAssistantVizFullscreenOpen,
    clearAssistantChat,
    selectAssistantVisualization,
    sendAssistantMessage,
  } = useMockStore();

  const { messages, layoutMode, activeVisualizationId } = assistantSession;

  const [draftMessage, setDraftMessage] = useState("");
  const [pendingChoice, setPendingChoice] = useState<string | null>(null);
  const [scrollToVizId, setScrollToVizId] = useState<string | undefined>();

  const userMessageCount = messages.filter((m) => m.role === "user").length;
  const showStarters = userMessageCount === 0;

  const handleStarterSelect = (prompt: string | null) => {
    setPendingChoice(prompt);
    setDraftMessage(prompt ?? "");
  };

  const handleSend = (text: string) => {
    setDraftMessage("");
    setPendingChoice(null);
    sendAssistantMessage(text);
  };

  const handleNewChat = () => {
    setDraftMessage("");
    setPendingChoice(null);
    setScrollToVizId(undefined);
    clearAssistantChat();
  };

  const handleSelectVisualization = (messageId: string) => {
    selectAssistantVisualization(messageId);
    setScrollToVizId(messageId);
  };

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col gap-3">
      <AssistantToolbar
        layoutMode={layoutMode}
        onNewChat={handleNewChat}
        onExpandViz={() => setAssistantVizFullscreenOpen(true)}
        canExpandViz={
          layoutMode === "split" && !!assistantLatestVisualization
        }
      />

      <div
        className={cn(
          "flex min-h-0 flex-1 transition-all duration-300",
          layoutMode === "split"
            ? "flex-col md:flex-row md:gap-0"
            : "flex-col items-center justify-center gap-4"
        )}
      >
        {layoutMode === "split" && (
          <AssistantCenterStage
            layoutMode={layoutMode}
            visualizationHistory={assistantVisualizationHistory}
            activeVisualizationId={activeVisualizationId}
            scrollToMessageId={scrollToVizId}
            showStarters={false}
            selectedStarter={pendingChoice}
            onStarterSelect={handleStarterSelect}
            startersDisabled={assistantIsSending}
            className="min-h-[40vh] md:min-h-0 md:border-r md:border-border/40"
          />
        )}

        {layoutMode === "centered" && (
          <AssistantCenterStage
            layoutMode={layoutMode}
            visualizationHistory={assistantVisualizationHistory}
            showStarters={showStarters}
            selectedStarter={pendingChoice}
            onStarterSelect={handleStarterSelect}
            startersDisabled={assistantIsSending}
          />
        )}

        <AssistantChatPanel
          messages={messages}
          isSending={assistantIsSending}
          layoutMode={layoutMode}
          activeVisualizationId={activeVisualizationId}
          onSend={handleSend}
          onSelectVisualization={handleSelectVisualization}
          input={draftMessage}
          onInputChange={setDraftMessage}
          pendingChoice={pendingChoice}
          onPendingChoiceChange={setPendingChoice}
          className={cn(
            layoutMode === "split" &&
              "border-t border-border/40 md:border-t-0 md:shrink-0"
          )}
        />
      </div>

      <VizFullscreenDialog
        open={assistantVizFullscreenOpen}
        onOpenChange={setAssistantVizFullscreenOpen}
        visualization={assistantLatestVisualization}
      />
    </div>
  );
}
