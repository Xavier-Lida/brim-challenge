type ChartPoint = { name: string; value: number };
type PieSegment = { name: string; value: number };
type TableShape = { columns: string[]; rows: string[][] };
type KpiShape = { value: string; label: string; change?: string };

const LABEL_KEYS = [
  "name",
  "label",
  "department",
  "employee_name",
  "month",
  "category",
  "merchant",
  "merchant_name",
];

const VALUE_KEYS = [
  "total",
  "value",
  "spend",
  "amount",
  "count",
  "flags",
  "avg_severity",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pickLabelKey(row: Record<string, unknown>): string | undefined {
  for (const key of LABEL_KEYS) {
    if (key in row && typeof row[key] === "string") return key;
  }
  return Object.keys(row).find((key) => typeof row[key] === "string");
}

function pickValueKey(row: Record<string, unknown>): string | undefined {
  for (const key of VALUE_KEYS) {
    if (key in row && typeof row[key] === "number") return key;
  }
  return Object.keys(row).find((key) => typeof row[key] === "number");
}

function rowToChartPoint(row: Record<string, unknown>): ChartPoint | null {
  const labelKey = pickLabelKey(row);
  const valueKey = pickValueKey(row);
  if (!labelKey || !valueKey) return null;
  const name = String(row[labelKey]);
  const value = Number(row[valueKey]);
  if (!Number.isFinite(value)) return null;
  return { name, value };
}

function normalizeFromLabelsValues(data: unknown): ChartPoint[] {
  if (!isRecord(data)) return [];
  const labels = data.labels;
  const values = data.values;
  if (!Array.isArray(labels) || !Array.isArray(values)) return [];
  return labels.map((label, index) => ({
    name: String(label),
    value: Number(values[index] ?? 0),
  }));
}

function normalizeFromRecordRows(data: unknown): ChartPoint[] {
  if (!Array.isArray(data)) return [];
  return data
    .map((row) => (isRecord(row) ? rowToChartPoint(row) : null))
    .filter((point): point is ChartPoint => point !== null);
}

// Canonical, server-authoritative shape: { series: [{ name, value }] }
function normalizeFromSeries(data: unknown): ChartPoint[] {
  if (!isRecord(data) || !Array.isArray(data.series)) return [];
  return data.series
    .map((point) => {
      if (!isRecord(point)) return null;
      const value = Number(point.value);
      if (!Number.isFinite(value)) return null;
      return { name: String(point.name ?? ""), value };
    })
    .filter((point): point is ChartPoint => point !== null);
}

export function normalizeSeriesChartData(data: unknown): ChartPoint[] {
  const fromSeries = normalizeFromSeries(data);
  if (fromSeries.length > 0) return fromSeries;
  // Legacy tolerance: { labels, values } or array-of-row-objects.
  const fromLabels = normalizeFromLabelsValues(data);
  if (fromLabels.length > 0) return fromLabels;
  return normalizeFromRecordRows(data);
}

export function normalizePieChartData(data: unknown): PieSegment[] {
  if (isRecord(data) && Array.isArray(data.segments)) {
    return data.segments
      .map((segment) => {
        if (!isRecord(segment)) return null;
        const name =
          typeof segment.name === "string"
            ? segment.name
            : typeof segment.label === "string"
              ? segment.label
              : null;
        const value =
          typeof segment.value === "number"
            ? segment.value
            : typeof segment.total === "number"
              ? segment.total
              : null;
        if (!name || value === null) return null;
        return { name, value };
      })
      .filter((segment): segment is PieSegment => segment !== null);
  }

  return normalizeFromRecordRows(data).map(({ name, value }) => ({ name, value }));
}

export function normalizeTableData(data: unknown): TableShape {
  if (isRecord(data) && Array.isArray(data.columns) && Array.isArray(data.rows)) {
    return {
      columns: data.columns.map(String),
      rows: data.rows.map((row) =>
        Array.isArray(row) ? row.map(String) : [String(row)]
      ),
    };
  }

  if (Array.isArray(data) && data.every(isRecord)) {
    const columns = Object.keys(data[0] ?? {});
    const rows = data.map((row) => columns.map((col) => String(row[col] ?? "")));
    return { columns, rows };
  }

  return { columns: [], rows: [] };
}

export function normalizeKpiData(data: unknown): KpiShape | null {
  if (!isRecord(data)) return null;
  const value = data.value;
  const label = data.label;
  if (typeof value !== "string" && typeof value !== "number") return null;
  if (typeof label !== "string") return null;
  return {
    value: String(value),
    label,
    change: typeof data.change === "string" ? data.change : undefined,
  };
}
