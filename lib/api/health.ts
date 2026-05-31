import { apiFetch } from "@/lib/api/client";

export function healthCheck() {
  return apiFetch<{ status: string }>("/health");
}
