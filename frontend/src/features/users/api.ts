import type { UserRow } from "@/features/users/types";
import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

export function listUsers(query: PageQuery) {
  const qs = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  return apiClient<OffsetPage<UserRow>>(`/users?${qs.toString()}`);
}
