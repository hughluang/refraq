import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";
import type { CatalogJoin, JoinPathResult } from "@/features/sources/types";

export function listObjectJoins(
  objectId: string,
  params?: { limit?: number; offset?: number },
) {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<OffsetPage<CatalogJoin>>(
    `/objects/${objectId}/joins${suffix}`,
  );
}

export function createJoin(body: {
  from_column_id: string;
  to_column_id: string;
  evidence: string;
  join_kind?: string;
  join_expression?: string | null;
}) {
  return apiClient<{ join: CatalogJoin }>("/joins", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchJoin(
  joinId: string,
  body: {
    evidence: string;
    join_kind?: string;
    join_expression?: string | null;
  },
) {
  return apiClient<{ join: CatalogJoin }>(`/joins/${joinId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function rejectJoin(joinId: string) {
  return apiClient<{ join: CatalogJoin }>(`/joins/${joinId}/reject`, {
    method: "POST",
  });
}

export function restoreJoin(joinId: string) {
  return apiClient<{ join: CatalogJoin }>(`/joins/${joinId}/restore`, {
    method: "POST",
  });
}

export function deleteJoin(joinId: string) {
  return apiClient<void>(`/joins/${joinId}`, { method: "DELETE" });
}

export function getJoinPath(params: {
  start: string;
  target?: string;
  q?: string;
  max_hops?: number;
  top_targets?: number;
}) {
  const qs = new URLSearchParams();
  qs.set("start", params.start);
  if (params.target) qs.set("target", params.target);
  if (params.q) qs.set("q", params.q);
  if (params.max_hops != null) qs.set("max_hops", String(params.max_hops));
  if (params.top_targets != null) {
    qs.set("top_targets", String(params.top_targets));
  }
  return apiClient<JoinPathResult>(`/joins/path?${qs.toString()}`);
}
