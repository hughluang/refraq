import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

import type {
  Tag,
  TagCreateBody,
  TagPatchBody,
  TagSubject,
  TagSummary,
} from "@/features/tags/types";

function querySuffix(params?: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) continue;
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export function listTags(params?: {
  q?: string;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}) {
  const { signal, ...query } = params ?? {};
  return apiClient<OffsetPage<TagSummary>>(`/tags${querySuffix(query)}`, { signal });
}

export function getTag(id: string, init?: { signal?: AbortSignal }) {
  return apiClient<{ tag: Tag }>(`/tags/${id}`, { signal: init?.signal });
}

export function listTagSubjects(
  tagId: string,
  params?: { limit?: number; offset?: number; signal?: AbortSignal },
) {
  const { signal, ...query } = params ?? {};
  return apiClient<OffsetPage<TagSubject>>(
    `/tags/${tagId}/subjects${querySuffix(query)}`,
    { signal },
  );
}

export function createTag(body: TagCreateBody) {
  return apiClient<{ tag: Tag }>("/tags", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchTag(id: string, body: TagPatchBody) {
  return apiClient<{ tag: Tag }>(`/tags/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteTag(id: string) {
  return apiClient<void>(`/tags/${id}`, { method: "DELETE" });
}
