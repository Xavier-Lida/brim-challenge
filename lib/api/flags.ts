import { apiFetch } from "@/lib/api/client";
import { normalizeFlagsPage } from "@/lib/api/pagination";
import type { FlagsPage } from "@/lib/types/brim";

export const FLAGS_PAGE_SIZE = 100;

export function getFlags(params?: { limit?: number; offset?: number }) {
  const limit = params?.limit ?? FLAGS_PAGE_SIZE;
  const offset = params?.offset ?? 0;
  return apiFetch<unknown>("/api/flags", {
    params: { limit, offset },
  }).then((data) => normalizeFlagsPage(data, limit, offset));
}

export function markFlagReviewed(flagId: string) {
  return apiFetch<{ id: string; reviewed: boolean }>(
    `/api/flags/${flagId}/reviewed`,
    { method: "PATCH" }
  );
}
