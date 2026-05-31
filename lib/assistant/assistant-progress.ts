import type { AssistantProgressStep } from "@/lib/types/brim";

export const DEFAULT_PROGRESS_STEPS: AssistantProgressStep[] = [
  { id: "analyze", label: "Analyzing your question", status: "active" },
  { id: "query", label: "Querying spend data", status: "pending" },
  { id: "chart", label: "Building visualization", status: "pending" },
  { id: "write", label: "Writing the answer", status: "pending" },
];

export function createInitialProgressSteps(): AssistantProgressStep[] {
  return DEFAULT_PROGRESS_STEPS.map((step) => ({ ...step }));
}

function setStepStatus(
  steps: AssistantProgressStep[],
  id: string,
  status: AssistantProgressStep["status"]
): AssistantProgressStep[] {
  return steps.map((step) =>
    step.id === id ? { ...step, status } : step
  );
}

function markDoneThrough(
  steps: AssistantProgressStep[],
  throughId: string
): AssistantProgressStep[] {
  const order = ["analyze", "query", "chart", "write"];
  const throughIndex = order.indexOf(throughId);
  return steps.map((step) => {
    const idx = order.indexOf(step.id);
    if (idx < throughIndex) return { ...step, status: "done" as const };
    if (idx === throughIndex) return { ...step, status: "active" as const };
    return { ...step, status: "pending" as const };
  });
}

export function applyProgressPhase(
  steps: AssistantProgressStep[],
  phase: string
): AssistantProgressStep[] {
  switch (phase) {
    case "loading_data":
    case "planning":
      return markDoneThrough(
        setStepStatus(steps, "analyze", "active"),
        "analyze"
      );
    case "running_query":
    case "repairing_sql":
      return markDoneThrough(
        setStepStatus(
          setStepStatus(steps, "analyze", "done"),
          "query",
          "active"
        ),
        "query"
      );
    case "writing":
    case "degraded":
      return markDoneThrough(
        setStepStatus(
          setStepStatus(
            setStepStatus(steps, "analyze", "done"),
            "query",
            "done"
          ),
          "chart",
          "done"
        ),
        "write"
      );
    default:
      return steps;
  }
}

export function applyVisualizationProgress(
  steps: AssistantProgressStep[]
): AssistantProgressStep[] {
  return steps.map((step) => {
    if (step.id === "analyze" || step.id === "query" || step.id === "chart") {
      return { ...step, status: "done" };
    }
    if (step.id === "write") {
      return { ...step, status: "pending" };
    }
    return step;
  });
}

export function applyTextDeltaProgress(
  steps: AssistantProgressStep[]
): AssistantProgressStep[] {
  return steps.map((step) =>
    step.id === "write"
      ? { ...step, status: "active" }
      : step.status === "pending"
        ? step
        : { ...step, status: "done" }
  );
}

export function completeAllProgress(
  steps: AssistantProgressStep[]
): AssistantProgressStep[] {
  return steps.map((step) => ({ ...step, status: "done" as const }));
}
