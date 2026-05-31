import { apiFetch } from "@/lib/api/client";
import type { Notification } from "@/lib/types/brim";

export async function getNotifications(unread = false): Promise<Notification[]> {
  return apiFetch<Notification[]>("/api/notifications", {
    params: { unread },
  });
}

export async function markNotificationReadApi(
  id: string
): Promise<{ id: string; read: boolean }> {
  return apiFetch<{ id: string; read: boolean }>(
    `/api/notifications/${id}/read`,
    { method: "PATCH" }
  );
}
