import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

import type { Webhook, WebhookTestResult } from "@/features/webhooks/types";

function querySuffix(params?: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export function listWebhooks(params?: { q?: string; limit?: number; offset?: number }) {
  return apiClient<OffsetPage<Webhook>>(`/webhooks${querySuffix(params)}`);
}

export function getWebhook(id: string) {
  return apiClient<{ webhook: Webhook }>(`/webhooks/${id}`);
}

export function createWebhook(body: { name: string; url: string; secret?: string | null }) {
  return apiClient<{ webhook: Webhook }>("/webhooks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchWebhook(
  id: string,
  body: { name?: string; url?: string; secret?: string | null },
) {
  return apiClient<{ webhook: Webhook }>(`/webhooks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteWebhook(id: string) {
  return apiClient<void>(`/webhooks/${id}`, { method: "DELETE" });
}

export function testWebhook(id: string) {
  return apiClient<WebhookTestResult>(`/webhooks/${id}/test`, { method: "POST" });
}
