import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

import type {
  InboundCredential,
  InboundCredentialCreate,
  InboundCredentialPatch,
} from "@/features/inbound-credentials/types";

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

export function listInboundCredentials(params?: { q?: string; limit?: number; offset?: number }) {
  return apiClient<OffsetPage<InboundCredential>>(`/inbound-credentials${querySuffix(params)}`);
}

export function getInboundCredential(id: string) {
  return apiClient<{ inbound_credential: InboundCredential }>(`/inbound-credentials/${id}`);
}

export function createInboundCredential(body: InboundCredentialCreate) {
  return apiClient<{ inbound_credential: InboundCredential }>("/inbound-credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchInboundCredential(id: string, body: InboundCredentialPatch) {
  return apiClient<{ inbound_credential: InboundCredential }>(`/inbound-credentials/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteInboundCredential(id: string) {
  return apiClient<void>(`/inbound-credentials/${id}`, { method: "DELETE" });
}
