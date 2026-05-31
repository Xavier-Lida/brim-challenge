import { apiFetch } from "@/lib/api/client";
import type { MapEmployee, MapPurchasesResponse } from "@/lib/types/map";

export function getMapEmployees() {
  return apiFetch<MapEmployee[]>("/api/map/employees");
}

export function getMapPurchases(params: {
  employee_ids: string[];
  date_from?: string;
  date_to?: string;
}) {
  return apiFetch<MapPurchasesResponse>("/api/map/purchases", {
    params: {
      employee_ids: params.employee_ids.join(","),
      date_from: params.date_from,
      date_to: params.date_to,
    },
  });
}
