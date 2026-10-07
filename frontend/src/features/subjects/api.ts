import type {
  SubjectAttribute,
  SubjectValues,
  UserGroup,
  UserSubjectValues,
} from "@/features/subjects/types";
import type { UserRow } from "@/features/users/types";
import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

function pageQuery(query: PageQuery, extra?: Record<string, string | undefined>) {
  const qs = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (extra) {
    for (const [key, value] of Object.entries(extra)) {
      if (value) qs.set(key, value);
    }
  }
  return qs.toString();
}

export function listUserGroups(query: PageQuery & { q?: string }) {
  return apiClient<OffsetPage<UserGroup>>(
    `/user-groups?${pageQuery(query, { q: query.q })}`,
  );
}

export function createUserGroup(body: {
  key: string;
  name: string;
  description?: string | null;
}) {
  return apiClient<{ group: UserGroup }>("/user-groups", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getUserGroup(id: string) {
  return apiClient<{ group: UserGroup }>(`/user-groups/${id}`);
}

export function patchUserGroup(
  id: string,
  body: { name?: string; description?: string | null },
) {
  return apiClient<{ group: UserGroup }>(`/user-groups/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteUserGroup(id: string) {
  return apiClient<void>(`/user-groups/${id}`, { method: "DELETE" });
}

export function listGroupMembers(id: string, query: PageQuery) {
  return apiClient<OffsetPage<UserRow>>(
    `/user-groups/${id}/members?${pageQuery(query)}`,
  );
}

export function addGroupMember(groupId: string, userId: string) {
  return apiClient<void>(`/user-groups/${groupId}/members/${userId}`, {
    method: "PUT",
  });
}

export function removeGroupMember(groupId: string, userId: string) {
  return apiClient<void>(`/user-groups/${groupId}/members/${userId}`, {
    method: "DELETE",
  });
}

export function getGroupSubjectValues(id: string) {
  return apiClient<{ values: SubjectValues }>(
    `/user-groups/${id}/subject-attributes`,
  );
}

export function putGroupSubjectValues(id: string, values: SubjectValues) {
  return apiClient<{ values: SubjectValues }>(
    `/user-groups/${id}/subject-attributes`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ values }),
    },
  );
}

export function listSubjectAttributes(query: PageQuery) {
  return apiClient<OffsetPage<SubjectAttribute>>(
    `/subject-attributes?${pageQuery(query)}`,
  );
}

export function createSubjectAttribute(body: {
  key: string;
  name: string;
  description?: string | null;
  value_type: SubjectAttribute["value_type"];
  dictionary_id?: string | null;
  multi_value: boolean;
}) {
  return apiClient<{ subject_attribute: SubjectAttribute }>("/subject-attributes", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchSubjectAttribute(
  id: string,
  body: { name?: string; description?: string | null; multi_value?: boolean },
) {
  return apiClient<{ subject_attribute: SubjectAttribute }>(
    `/subject-attributes/${id}`,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteSubjectAttribute(id: string) {
  return apiClient<void>(`/subject-attributes/${id}`, { method: "DELETE" });
}

export function getUser(id: string) {
  return apiClient<{ user: UserRow }>(`/users/${id}`);
}

export function getUserGroups(userId: string) {
  return apiClient<{ groups: UserGroup[] }>(`/users/${userId}/groups`);
}

export function putUserGroups(userId: string, groupIds: string[]) {
  return apiClient<{ groups: UserGroup[] }>(`/users/${userId}/groups`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group_ids: groupIds }),
  });
}

export function getUserSubjectValues(userId: string) {
  return apiClient<UserSubjectValues>(`/users/${userId}/subject-attributes`);
}

export function putUserSubjectValues(userId: string, values: SubjectValues) {
  return apiClient<UserSubjectValues>(`/users/${userId}/subject-attributes`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ values }),
  });
}
