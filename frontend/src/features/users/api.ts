import type { UserRow } from "@/features/users/types";
import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

export function updateUserRole(userId: string, roleId: string | null) {
  return apiClient<{ user: UserRow }>(`/users/${userId}/role`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ role_id: roleId }),
  });
}

export function listUsers(
  query: PageQuery & {
    q?: string;
    identity_source?: UserRow["identity_source"];
    signal?: AbortSignal;
  },
) {
  const qs = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.q) qs.set("q", query.q);
  if (query.identity_source) qs.set("identity_source", query.identity_source);
  return apiClient<OffsetPage<UserRow>>(`/users?${qs.toString()}`, {
    signal: query.signal,
  });
}
