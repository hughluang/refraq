import type { RoleRow } from "@/features/roles/types";
import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

export function listRoles(query: PageQuery) {
  const qs = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  return apiClient<OffsetPage<RoleRow>>(`/roles?${qs.toString()}`);
}
