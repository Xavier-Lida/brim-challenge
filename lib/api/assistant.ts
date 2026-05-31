import { apiFetch } from "@/lib/api/client";
import { mockLlm } from "@/lib/api/config";
import type { AssistantMessage } from "@/lib/types/brim";

export type AssistantHistoryTurn = {
  question: string;
  summary?: string;
  text?: string;
};

export type AssistantResponse = Omit<
  AssistantMessage,
  "id" | "role" | "created_at" | "streaming"
>;

export async function askAssistant(
  question: string,
  history: AssistantHistoryTurn[] = [],
  options?: {
    mock_llm?: boolean;
    signal?: AbortSignal;
  }
): Promise<AssistantResponse> {
  return apiFetch<AssistantResponse>("/api/assistant", {
    method: "POST",
    params: { mock_llm: options?.mock_llm ?? mockLlm },
    signal: options?.signal,
    body: { question, history },
  });
}
