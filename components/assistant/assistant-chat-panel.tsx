"use client";

import { useEffect, useRef, useState } from "react";
import { PaperPlaneRightIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AssistantFollowUpChoices } from "@/components/assistant/assistant-follow-up-choices";
import { AssistantMessageBubble } from "@/components/assistant/assistant-message";
import { resolveFollowUpChoices } from "@/lib/assistant/follow-up-catalog";
import type { AssistantMessage, Visualization } from "@/lib/types/brim";
import { cn } from "@/lib/utils";

type AssistantChatPanelProps = {
  messages: AssistantMessage[];
  isSending: boolean;
  layoutMode: "centered" | "split";
  activeVisualizationId?: string;
  onSend: (text: string) => void;
  onSelectVisualization?: (messageId: string) => void;
  input?: string;
  onInputChange?: (value: string) => void;
  pendingChoice?: string | null;
  onPendingChoiceChange?: (choice: string | null) => void;
  className?: string;
};

export function AssistantChatPanel({
  messages,
  isSending,
  layoutMode,
  activeVisualizationId,
  onSend,
  onSelectVisualization,
  input: controlledInput,
  onInputChange,
  pendingChoice: controlledPendingChoice,
  onPendingChoiceChange,
  className,
}: AssistantChatPanelProps) {
  const [internalInput, setInternalInput] = useState("");
  const [internalPendingChoice, setInternalPendingChoice] = useState<
    string | null
  >(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const input = controlledInput ?? internalInput;
  const setInput = onInputChange ?? setInternalInput;
  const pendingChoice = controlledPendingChoice ?? internalPendingChoice;
  const setPendingChoice =
    onPendingChoiceChange ?? setInternalPendingChoice;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && !m.streaming);

  const lastAssistantId = lastAssistant?.id;

  useEffect(() => {
    setPendingChoice(null);
  }, [lastAssistantId, setPendingChoice]);

  useEffect(() => {
    if (isSending) setPendingChoice(null);
  }, [isSending, setPendingChoice]);

  const handleFollowUpSelect = (choice: string | null) => {
    setPendingChoice(choice);
    if (choice) setInput(choice);
    else setInput("");
  };

  const sessionVisualizations = messages
    .map((m) => m.visualization)
    .filter((v): v is Visualization => Boolean(v));

  const followUpContext = (() => {
    if (!lastAssistant) return undefined;
    const assistantIndex = messages.findIndex((m) => m.id === lastAssistant.id);
    const priorUser = [...messages.slice(0, assistantIndex)]
      .reverse()
      .find((m) => m.role === "user");
    return {
      lastQuestion: priorUser?.text ?? lastAssistant.sourceQuestion ?? "",
      vizType: lastAssistant.visualization?.type,
    };
  })();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isSending) return;
    setInput("");
    setPendingChoice(null);
    onSend(trimmed);
  };

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col",
        layoutMode === "centered" ? "w-full max-w-xl" : "h-full w-full md:w-[360px]",
        className
      )}
    >
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-3 p-1 pr-3">
          {messages.map((msg) => (
            <AssistantMessageBubble
              key={msg.id}
              message={msg}
              sessionVisualizations={sessionVisualizations}
              onSelectVisualization={
                layoutMode === "split" ? onSelectVisualization : undefined
              }
              isActiveVisualization={msg.id === activeVisualizationId}
            />
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {lastAssistant?.followUpSuggestions && !isSending && (
        <AssistantFollowUpChoices
          choices={resolveFollowUpChoices(
            lastAssistant.followUpSuggestions,
            followUpContext
          )}
          selected={pendingChoice}
          onSelect={handleFollowUpSelect}
        />
      )}

      <form
        onSubmit={handleSubmit}
        className="mt-auto flex gap-2 border-t border-border/40 bg-background/90 p-3 backdrop-blur-sm"
      >
        <Input
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            if (pendingChoice && e.target.value !== pendingChoice) {
              setPendingChoice(null);
            }
          }}
          placeholder="Ask about spend, flags, or policy..."
          disabled={isSending}
          className="border-border/60 bg-muted/50"
        />
        <Button type="submit" disabled={isSending || !input.trim()}>
          <PaperPlaneRightIcon data-icon="inline-start" />
          Send
        </Button>
      </form>
    </div>
  );
}
