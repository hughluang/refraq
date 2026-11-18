import { apiClient } from "@/lib/api";
import type { PendingOperation } from "@/features/mirrors/types";

export type NotificationChannel = {
  configured: boolean;
  primary_configured: boolean;
  fallback_configured: boolean;
  responder: string | null;
  delivery_state: Record<string, unknown>;
  last_test_at: string | null;
  last_fault_code: string | null;
};
export type NotificationRoute = { https_url: string; credential: { header_name: string; secret: string } };
export type NotificationReplacement = { primary: NotificationRoute; fallback: NotificationRoute; responder: string };

export function getNotificationChannel() {
  return apiClient<{ channel: NotificationChannel }>("/settings/notification-channel");
}
export function replaceNotificationChannel(config: NotificationReplacement) {
  return apiClient<{ channel: NotificationChannel }>("/settings/notification-channel", {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(config),
  });
}
export function testNotificationChannel() {
  return apiClient<PendingOperation>("/settings/notification-channel/test", { method: "POST" });
}
