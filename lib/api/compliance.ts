import { apiFetch } from "@/lib/api/client";
import { mockLlm } from "@/lib/api/config";

type ComplianceScanParams = {
  mock_llm?: boolean;
  limit?: number;
  employee_id?: string;
};

type ComplianceScanResult = {
  feature: string;
  flag_count: number;
  strike_count: number;
  employee_id?: string | null;
  summary: {
    by_severity: { high: number; medium: number; low: number };
    repeat_offenders: unknown[];
    policy: string;
  } | null;
  persisted: {
    flags_inserted: number;
    strikes_inserted: number;
    notifications_upserted: number;
  };
};

export type { ComplianceScanParams, ComplianceScanResult };

export function runComplianceScan(params: ComplianceScanParams = {}) {
  return apiFetch<ComplianceScanResult>("/api/compliance/scan", {
    method: "POST",
    params: {
      mock_llm: params.mock_llm ?? mockLlm,
      limit: params.limit,
      employee_id: params.employee_id,
    },
  });
}
