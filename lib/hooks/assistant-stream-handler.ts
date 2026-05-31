import {
  applyProgressPhase,
  applyTextDeltaProgress,
  applyVisualizationProgress,
  completeAllProgress,
  createInitialProgressSteps,
} from "@/lib/assistant/assistant-progress";
import type { AssistantStreamEvent } from "@/lib/api/assistant-stream";
import type { AssistantMessage } from "@/lib/types/brim";

export type PatchAssistantMessage = (
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
) => void;

export function createAssistantStreamHandler(
  assistantId: string,
  patch: PatchAssistantMessage
) {
  let accumulated = "";
  let settled = false;
  let steps = createInitialProgressSteps();

  const handler = (event: AssistantStreamEvent) => {
    switch (event.type) {
      case "status": {
        steps = applyProgressPhase(steps, event.phase);
        patch(assistantId, {
          activity: event.message,
          progressSteps: steps,
        });
        break;
      }
      case "text_delta": {
        accumulated += event.delta;
        steps = applyTextDeltaProgress(steps);
        patch(assistantId, {
          text: accumulated,
          activity: undefined,
          progressSteps: steps,
          streaming: true,
        });
        break;
      }
      case "visualization": {
        steps = applyVisualizationProgress(steps);
        patch(assistantId, {
          visualization: event.visualization,
          progressSteps: steps,
        });
        break;
      }
      case "follow_up":
        patch(assistantId, {
          followUpSuggestions: event.suggestions,
        });
        break;
      case "error":
        settled = true;
        steps = completeAllProgress(steps);
        patch(assistantId, {
          text: accumulated || event.message,
          progressSteps: steps,
          streaming: false,
        });
        break;
      case "done":
        settled = true;
        steps = completeAllProgress(steps);
        patch(assistantId, {
          progressSteps: steps,
          streaming: false,
        });
        break;
    }
  };

  return {
    handler,
    getAccumulated: () => accumulated,
    isSettled: () => settled,
    markSettled: () => {
      settled = true;
    },
    finalizeUnsettled: () => {
      if (!settled) {
        patch(assistantId, { streaming: false });
      }
    },
    setErrorText: (text: string) => {
      steps = completeAllProgress(steps);
      patch(assistantId, {
        text,
        progressSteps: steps,
        streaming: false,
      });
    },
  };
}
