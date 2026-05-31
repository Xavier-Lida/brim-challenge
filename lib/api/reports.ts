import { apiFetch } from "@/lib/api/client";
import { API_BASE_URL, mockLlm } from "@/lib/api/config";
import { normalizeReportsPage } from "@/lib/api/pagination";
import type { ExpenseReport, ReportsPage } from "@/lib/types/brim";

export const REPORTS_PAGE_SIZE = 100;

export function getReports(params?: { limit?: number; offset?: number }) {
  const limit = params?.limit ?? REPORTS_PAGE_SIZE;
  const offset = params?.offset ?? 0;
  return apiFetch<unknown>("/api/reports", {
    params: { limit, offset },
  }).then((data) => normalizeReportsPage(data, limit, offset));
}

type GenerateReportsParams = {
  mock_llm?: boolean;
  gap_days?: number;
};

type GenerateReportsBody = {
  event_group_id?: string | null;
};

type GenerateReportsResult = {
  feature: string;
  model: string;
  report_count: number;
  expense_reports: ExpenseReport[];
  persisted: {
    event_groups_updated: number;
    reports_upserted: number;
  };
};

export function generateReports(
  body: GenerateReportsBody = {},
  params: GenerateReportsParams = {}
) {
  return apiFetch<GenerateReportsResult>("/api/reports/generate", {
    method: "POST",
    body,
    params: {
      mock_llm: params.mock_llm ?? mockLlm,
      gap_days: params.gap_days,
    },
  });
}

/**
 * Resolve the downloadable PDF URL for a report. Uses the backend-provided
 * `pdf_url` when present (resolved against the API origin), otherwise falls
 * back to the on-demand generation endpoint.
 */
export function resolveReportPdfUrl(report: ExpenseReport): string {
  if (report.pdf_url) {
    return new URL(report.pdf_url, API_BASE_URL).toString();
  }
  return new URL(`/api/reports/${report.id}/pdf`, API_BASE_URL).toString();
}

function pdfFilename(report: ExpenseReport): string {
  const base = (report.title || `report-${report.id}`)
    .replace(/[^\w.-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `${base || report.id}.pdf`;
}

/**
 * Fetch the backend-generated PDF and trigger a browser download. Throws an
 * ApiError-like Error on failure so callers can surface a toast.
 */
export async function downloadReportPdf(report: ExpenseReport): Promise<void> {
  const url = resolveReportPdfUrl(report);

  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/pdf" } });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "Network error";
    throw new Error(`Cannot reach the PDF service (${reason}).`);
  }

  if (!response.ok) {
    throw new Error(`Could not export the PDF (status ${response.status}).`);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = pdfFilename(report);
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export type { ReportsPage };
