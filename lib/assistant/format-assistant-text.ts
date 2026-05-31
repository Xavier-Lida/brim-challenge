import { STATIC_ENTITY_VOCABULARY } from "@/lib/assistant/entity-vocabulary";

const BOLD_PATTERNS: RegExp[] = [
  /\$[\d,]+(?:\.\d{2})?/g,
  /\d{1,3}(?:\s\d{3})*,\d{2}\s*\$/g,
  /(?:un crédit de|a credit of)\s+[\d\s,]+(?:,\d{2})?\s*\$?/gi,
  /[+-]?\d+(?:\.\d+)?%/g,
  /(?<=flags?\s|strikes?\s|transactions?\s|signalements?\s)\d{2,}/gi,
];

const GEO_PATTERNS: RegExp[] = [
  /\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2}\b/g,
  /\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*(?:Canada|United States|USA|France|UK|Mexico)\b/g,
];

type Span = { start: number; end: number; text: string; wrap: "**" | "_" };

function isInsideMarkup(text: string, index: number, marker: "**" | "_"): boolean {
  const before = text.slice(0, index);
  const count = (before.match(new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) ?? [])
    .length;
  return count % 2 === 1;
}

function overlaps(spans: Span[], start: number, end: number): boolean {
  return spans.some((s) => start < s.end && end > s.start);
}

function collectPatternSpans(
  text: string,
  pattern: RegExp,
  wrap: "**" | "_",
  spans: Span[]
): void {
  const re = new RegExp(pattern.source, pattern.flags);
  let match = re.exec(text);
  while (match !== null) {
    const start = match.index;
    const end = start + match[0].length;
    const marker = wrap;
    if (
      !isInsideMarkup(text, start, "**") &&
      !isInsideMarkup(text, start, "_") &&
      !overlaps(spans, start, end)
    ) {
      spans.push({ start, end, text: match[0], wrap: marker });
    }
    match = re.exec(text);
  }
}

function collectEntitySpans(
  text: string,
  entities: string[],
  spans: Span[]
): void {
  for (const entity of entities) {
    if (entity.length < 2) continue;
    const escaped = entity.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`\\b${escaped}\\b`, "gi");
    let match = re.exec(text);
    while (match !== null) {
      const start = match.index;
      const end = start + match[0].length;
      if (
        !isInsideMarkup(text, start, "**") &&
        !isInsideMarkup(text, start, "_") &&
        !overlaps(spans, start, end)
      ) {
        spans.push({ start, end, text: match[0], wrap: "_" });
      }
      match = re.exec(text);
    }
  }
}

export function formatAssistantText(
  text: string,
  entityHints: string[] = []
): string {
  if (!text.trim()) return text;

  const spans: Span[] = [];

  for (const pattern of BOLD_PATTERNS) {
    collectPatternSpans(text, pattern, "**", spans);
  }

  const entities = [...entityHints, ...STATIC_ENTITY_VOCABULARY];
  collectEntitySpans(text, entities, spans);

  for (const pattern of GEO_PATTERNS) {
    collectPatternSpans(text, pattern, "_", spans);
  }

  spans.sort((a, b) => b.start - a.start);
  let result = text;
  for (const span of spans) {
    const open = span.wrap;
    const close = span.wrap;
    result =
      result.slice(0, span.start) +
      `${open}${span.text}${close}` +
      result.slice(span.end);
  }
  return result;
}

/** @deprecated Use formatAssistantText */
export function emphasizeAssistantText(
  text: string,
  entityHints?: string[]
): string {
  return formatAssistantText(text, entityHints);
}
