import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";
import type { Mirror, PendingOperation, RecoveryRequest } from "./types";

export function listMirrors(params: { source_id?: string; status?: string; q?: string; limit: number; offset: number }) {
  const query = new URLSearchParams();
  if (params.source_id) query.set("source_id", params.source_id);
  if (params.status) query.set("status", params.status);
  if (params.q) query.set("q", params.q);
  query.set("limit", String(params.limit));
  query.set("offset", String(params.offset));
  return apiClient<OffsetPage<Mirror>>(`/mirrors?${query}`);
}

export function getMirror(id: string, signal?: AbortSignal) {
  return apiClient<{ mirror: Mirror; can_enable: boolean }>(`/mirrors/${encodeURIComponent(id)}`, { signal });
}

export function setMirrorEnabled(id: string, enabled: boolean, signal?: AbortSignal) {
  return apiClient<{ mirror: Mirror; operation_id: string }>(`/mirrors/${encodeURIComponent(id)}`, {
    method: "PATCH", signal, headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled }),
  });
}

export function requestRecovery(id: string, request: RecoveryRequest) {
  return apiClient<PendingOperation>(`/mirrors/${encodeURIComponent(id)}/recovery-requests`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request),
  });
}
