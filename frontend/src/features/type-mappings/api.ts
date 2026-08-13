import { apiClient } from "@/lib/api";

import type { PatchableNormalizedType, TypeMapping, TypeMappingOrigin } from "./types";

export function listTypeMappings(params?: {
  q?: string;
  engine?: string;
  origin?: TypeMappingOrigin;
  limit?: number;
  offset?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.engine) qs.set("engine", params.engine);
  if (params?.origin) qs.set("origin", params.origin);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<{
    items: TypeMapping[];
    total: number;
    limit: number;
    offset: number;
  }>(`/type-mappings${suffix}`);
}

export function patchTypeMapping(
  id: string,
  body: { normalized_type: PatchableNormalizedType },
) {
  return apiClient<{ mapping: TypeMapping }>(`/type-mappings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
