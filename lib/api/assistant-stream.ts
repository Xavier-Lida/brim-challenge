import { apiFetch } from "@/lib/api/client";
import { mockLlm } from "@/lib/api/config";
import type { AssistantHistoryTurn, AssistantResponse } from "@/lib/api/assistant";
import { askAssistant } from "@/lib/api/assistant";
import type { FollowUpSuggestion, Visualization } from "@/lib/types/brim";

import { API_BASE_URL } from "@/lib/api/config";

export type AssistantStreamEvent =
  | { type: "status"; phase: string; message: string }
  | { type: "text_delta"; delta: string }
  | { type: "visualization"; visualization: Visualization }
  | { type: "follow_up"; suggestions: FollowUpSuggestion[] }
  | { type: "done" }
  | { type: "error"; message: string };

const useStreamEndpoint =
  process.env.NEXT_PUBLIC_ASSISTANT_STREAM === "true" ||
  process.env.NEXT_PUBLIC_ASSISTANT_STREAM === "1";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseSseChunk(chunk: string): AssistantStreamEvent[] {
  const events: AssistantStreamEvent[] = [];
  const lines = chunk.split("\n");
  for (const line of lines) {
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (!payload || payload === "[DONE]") continue;
    try {
      events.push(JSON.parse(payload) as AssistantStreamEvent);
    } catch {
      // skip malformed events
    }
  }
  return events;
}

async function streamFromBackend(
  question: string,
  history: AssistantHistoryTurn[],
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const url = new URL("/api/assistant/stream", API_BASE_URL);
  if (mockLlm) url.searchParams.set("mock_llm", "true");

  const response = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ question, history }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Stream failed with status ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      for (const event of parseSseChunk(part)) {
        onEvent(event);
      }
    }
  }

  if (buffer.trim()) {
    for (const event of parseSseChunk(buffer)) {
      onEvent(event);
    }
  }
}

async function simulateTypingFromResponse(
  response: AssistantResponse,
  onEvent: (event: AssistantStreamEvent) => void
): Promise<void> {
  onEvent({
    type: "status",
    phase: "planning",
    message: "Analyzing your question…",
  });
  await sleep(550);
  onEvent({
    type: "status",
    phase: "running_query",
    message: "Querying spend data…",
  });
  await sleep(650);
  if (response.visualization) {
    onEvent({ type: "visualization", visualization: response.visualization });
    await sleep(500);
  }
  onEvent({
    type: "status",
    phase: "writing",
    message: "Writing the answer…",
  });
  await sleep(600);
  const tokens = response.text.match(/\S+\s*|\s+/g) ?? [response.text];
  for (const token of tokens) {
    onEvent({ type: "text_delta", delta: token });
    await sleep(28);
  }
  if (response.followUpSuggestions?.length) {
    onEvent({ type: "follow_up", suggestions: response.followUpSuggestions });
  }
  onEvent({ type: "done" });
}

export async function askAssistantStream(
  question: string,
  history: AssistantHistoryTurn[],
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  if (useStreamEndpoint) {
    try {
      await streamFromBackend(question, history, onEvent, signal);
      return;
    } catch {
      // fall through to JSON + simulated typing
    }
  }

  try {
    const response = await askAssistant(question, history, { signal });
    await simulateTypingFromResponse(response, onEvent);
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Assistant request failed";
    onEvent({ type: "error", message });
    onEvent({ type: "done" });
  }
}
