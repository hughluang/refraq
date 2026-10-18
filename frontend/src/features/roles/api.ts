import type { RoleRow } from "@/features/roles/types";
import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

export function listRoles(query: PageQuery & { q?: string; signal?: AbortSignal }) {
  const qs = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.q) qs.set("q", query.q);
  return apiClient<OffsetPage<RoleRow>>(`/roles?${qs.toString()}`, {
    signal: query.signal,
  });
}

export function getRole(id: string, init?: { signal?: AbortSignal }) {
  return apiClient<{ role: RoleRow }>(`/roles/${id}`, { signal: init?.signal });
}
