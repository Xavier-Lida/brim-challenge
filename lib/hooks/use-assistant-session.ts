"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { initialAssistantMessages } from "@/lib/mocks/fixtures";
import { generateId } from "@/lib/mocks/services";
import { createInitialProgressSteps } from "@/lib/assistant/assistant-progress";
import type {
  AssistantLayoutMode,
  AssistantMessage,
  AssistantSessionState,
  Visualization,
  VisualizationHistoryEntry,
} from "@/lib/types/brim";

const STORAGE_KEY = "brim-assistant-session";

function deriveLayoutMode(messages: AssistantMessage[]): AssistantLayoutMode {
  return messages.some((m) => m.visualization) ? "split" : "centered";
}

function getDefaultSession(): AssistantSessionState {
  return {
    messages: initialAssistantMessages,
    layoutMode: "centered",
    activeVisualizationId: undefined,
  };
}

function loadSession(): AssistantSessionState {
  if (typeof window === "undefined") return getDefaultSession();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaultSession();
    const parsed = JSON.parse(raw) as AssistantSessionState & {
      context?: unknown;
    };
    const messages = parsed.messages?.length ? parsed.messages : initialAssistantMessages;
    return {
      messages,
      layoutMode: deriveLayoutMode(messages),
      activeVisualizationId: parsed.activeVisualizationId,
    };
  } catch {
    return getDefaultSession();
  }
}

export type BeginAssistantMessageOptions = {
  sourceQuestion: string;
};

export function useAssistantSession() {
  const [session, setSession] = useState<AssistantSessionState>(getDefaultSession);
  const [hydrated, setHydrated] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [vizFullscreenOpen, setVizFullscreenOpen] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setSession(loadSession());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    }, 300);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [session, hydrated]);

  const visualizationHistory = useMemo((): VisualizationHistoryEntry[] => {
    return session.messages
      .filter((m) => m.visualization)
      .map((m) => ({
        messageId: m.id,
        visualization: m.visualization!,
        createdAt: m.created_at,
        sourceQuestion: m.sourceQuestion ?? "",
      }));
  }, [session.messages]);

  const activeVisualization = useMemo((): Visualization | undefined => {
    const targetId = session.activeVisualizationId;
    if (targetId) {
      const msg = session.messages.find((m) => m.id === targetId);
      if (msg?.visualization) return msg.visualization;
    }
    return visualizationHistory.at(-1)?.visualization;
  }, [
    session.messages,
    session.activeVisualizationId,
    visualizationHistory,
  ]);

  const latestVisualization = visualizationHistory.at(-1)?.visualization;

  const clearChat = useCallback(() => {
    setSession({
      messages: initialAssistantMessages,
      layoutMode: "centered",
      activeVisualizationId: undefined,
    });
    setVizFullscreenOpen(false);
  }, []);

  const selectVisualization = useCallback((messageId: string) => {
    setSession((prev) => ({
      ...prev,
      activeVisualizationId: messageId,
    }));
  }, []);

  const appendUserMessage = useCallback((text: string) => {
    const userMessage: AssistantMessage = {
      id: generateId("msg"),
      role: "user",
      text,
      created_at: new Date().toISOString(),
    };
    setSession((prev) => ({
      ...prev,
      messages: [...prev.messages, userMessage],
    }));
    return userMessage.id;
  }, []);

  const beginAssistantMessage = useCallback(
    (options: BeginAssistantMessageOptions) => {
      const id = generateId("msg");
      const assistantMessage: AssistantMessage = {
        id,
        role: "assistant",
        text: "",
        streaming: true,
        progressSteps: createInitialProgressSteps(),
        sourceQuestion: options.sourceQuestion,
        created_at: new Date().toISOString(),
      };
      setSession((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));
      return id;
    },
    []
  );

  const patchAssistantMessage = useCallback(
    (
      id: string,
      patch: Partial<
        Pick<
          AssistantMessage,
          | "text"
          | "activity"
          | "visualization"
          | "followUpSuggestions"
          | "progressSteps"
          | "streaming"
        >
      >
    ) => {
      setSession((prev) => {
        let activeVisualizationId = prev.activeVisualizationId;
        if (patch.visualization) {
          activeVisualizationId = id;
        }
        const definedPatch = Object.fromEntries(
          Object.entries(patch).filter(([, value]) => value !== undefined)
        ) as Partial<AssistantMessage>;
        const messages = prev.messages.map((m) =>
          m.id === id ? { ...m, ...definedPatch } : m
        );
        return {
          ...prev,
          messages,
          layoutMode: deriveLayoutMode(messages),
          activeVisualizationId,
        };
      });
    },
    []
  );

  const buildHistory = useCallback((messages: AssistantMessage[]) => {
    return messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-6)
      .reduce<{ question: string; summary: string }[]>((acc, msg, idx, arr) => {
        if (msg.role === "user") {
          const next = arr[idx + 1];
          acc.push({
            question: msg.text,
            summary: next?.role === "assistant" ? next.text : "",
          });
        }
        return acc;
      }, []);
  }, []);

  return {
    session,
    hydrated,
    isSending,
    setIsSending,
    activeVisualization,
    latestVisualization,
    visualizationHistory,
    vizFullscreenOpen,
    setVizFullscreenOpen,
    clearChat,
    selectVisualization,
    appendUserMessage,
    beginAssistantMessage,
    patchAssistantMessage,
    buildHistory,
    setSession,
  };
}

export type AssistantSessionApi = ReturnType<typeof useAssistantSession>;
