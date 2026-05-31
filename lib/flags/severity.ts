import type { TransactionFlag } from "@/lib/types/brim";

export type SeverityBand = "high" | "medium" | "low";

export function severityBand(weight: number): SeverityBand {
  if (weight >= 4) return "high";
  if (weight >= 2) return "medium";
  return "low";
}

const DOT_BY_WEIGHT: Record<number, string> = {
  1: "bg-muted-foreground/40",
  2: "bg-yellow-500",
  3: "bg-orange-500",
  4: "bg-red-500",
  5: "bg-red-700",
};

export function severityDotClass(weight: number): string {
  return DOT_BY_WEIGHT[Math.min(5, Math.max(1, weight))] ?? "bg-muted-foreground/40";
}

export function severityLabel(weight: number): string {
  switch (severityBand(weight)) {
    case "high":
      return "High";
    case "medium":
      return "Medium";
    default:
      return "Low";
  }
}

export function getSeverityCounts(flags: TransactionFlag[]): Record<SeverityBand, number> {
  return flags.reduce(
    (acc, flag) => {
      acc[severityBand(flag.weight)] += 1;
      return acc;
    },
    { high: 0, medium: 0, low: 0 } as Record<SeverityBand, number>
  );
}
