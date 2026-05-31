import type { Visualization } from "@/lib/types/brim";

const NUMERIC_CELL = /^-?\$?[\d,]+(?:\.\d+)?%?$/;

function isEntityCell(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length < 2) return false;
  if (NUMERIC_CELL.test(trimmed)) return false;
  return true;
}

export function extractEntityHints(
  visualization?: Visualization
): string[] {
  if (!visualization) return [];

  const hints = new Set<string>();

  if (visualization.type === "kpi") {
    if (visualization.data.label?.trim()) {
      hints.add(visualization.data.label.trim());
    }
  }

  if (
    visualization.type === "bar" ||
    visualization.type === "line"
  ) {
    for (const point of visualization.data.series) {
      if (point.name?.trim()) hints.add(point.name.trim());
    }
  }

  if (visualization.type === "pie") {
    for (const segment of visualization.data.segments) {
      if (segment.name?.trim()) hints.add(segment.name.trim());
    }
  }

  if (visualization.type === "table") {
    for (const row of visualization.data.rows) {
      for (const cell of row) {
        if (isEntityCell(cell)) hints.add(cell.trim());
      }
    }
  }

  return [...hints].sort((a, b) => b.length - a.length);
}

export function collectSessionEntityHints(
  visualizations: (Visualization | undefined)[]
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const viz of visualizations) {
    for (const hint of extractEntityHints(viz)) {
      const key = hint.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(hint);
    }
  }
  return out.sort((a, b) => b.length - a.length);
}
