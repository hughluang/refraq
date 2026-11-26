import { ApiError, apiClient } from "@/lib/api";
import type { CatalogObject, SemanticsChange, SemanticsChangeQuery } from "@/features/sources/types";
import type { OffsetPage } from "@/lib/pagination";
import type { MirrorReference } from "@/features/mirrors/types";

type CatalogSource = { id: string; key: string; name: string; engine: string | null };

export function listCatalogSources(opts: {
  source_id?: string; q?: string; limit?: number; offset?: number; signal?: AbortSignal;
}) {
  const params = new URLSearchParams();
  if (opts.source_id) params.set("source_id", opts.source_id);
  if (opts.q) params.set("q", opts.q);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  return apiClient<OffsetPage<CatalogSource>>(`/catalog/sources?${params}`, { signal: opts.signal });
}

export function listCatalogObjects(
  sourceId: string,
  q?: string,
  opts?: {
    limit?: number;
    offset?: number;
    object_type?: string;
    include_absent?: boolean;
    business_semantics_ready?: boolean;
    signal?: AbortSignal;
  },
) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.object_type) params.set("object_type", opts.object_type);
  if (opts?.include_absent != null) {
    params.set("include_absent", String(opts.include_absent));
  }
  if (opts?.business_semantics_ready != null) {
    params.set("business_semantics_ready", String(opts.business_semantics_ready));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiClient<{
    items: CatalogObject[];
    total: number;
    limit: number;
    offset: number;
  }>(`/sources/${encodeURIComponent(sourceId)}/objects${query}`, { signal: opts?.signal });
}

export type MirrorTable = {
  object_id: string;
  source_id: string;
  source_key: string;
  source_name: string;
  qualified_table: string;
  storage_destination: string;
  source_size_bytes: number | null;
  estimated_rows: number | null;
  mirror: CatalogObject["mirror"];
  snapshot_holder: MirrorReference | null;
  publication_wait: MirrorReference | null;
};

export function listMirrorTables(
  options: { source_id?: string; q?: string; object_id?: string; limit: number; offset: number },
  signal?: AbortSignal,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return apiClient<OffsetPage<MirrorTable>>(`/catalog/mirror-tables?${params}`, { signal });
}

export function getCatalogObject(objectId: string, signal?: AbortSignal) {
  return apiClient<{ object: CatalogObject }>(`/objects/${encodeURIComponent(objectId)}`, { signal });
}

export function setCatalogMirrorEnabled(objectId: string, enabled: boolean, signal: AbortSignal) {
  return apiClient<{ mirror: NonNullable<CatalogObject["mirror"]>; operation_id: string | null }>(
    `/objects/${encodeURIComponent(objectId)}/mirror`,
    { method: "PUT", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) },
  );
}

export function deleteCatalogMirror(objectId: string, token: string, signal: AbortSignal) {
  const query = new URLSearchParams({ delete_token: token });
  return apiClient<{ operation_id: string; state: "pending" } | undefined>(
    `/objects/${encodeURIComponent(objectId)}/mirror?${query}`, { method: "DELETE", signal },
  );
}

export async function resolveCatalogObject(objectRef: string, signal?: AbortSignal): Promise<{ object: CatalogObject | null }> {
  if (objectRef.startsWith("obj/")) {
    const parts = objectRef.split("/");
    if (parts.length !== 6 || parts.some((part) => !part)) return { object: null };
    try {
      const params = new URLSearchParams({ ref: objectRef });
      return await apiClient<{ object: CatalogObject }>(`/catalog/objects/resolve?${params}`, { signal });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return { object: null };
      }
      throw error;
    }
  }
  try {
    return await getCatalogObject(objectRef, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { object: null };
    }
    throw error;
  }
}

export function searchCatalogObjects(
  q: string,
  opts?: {
    source_id?: string;
    object_type?: string;
    limit?: number;
    offset?: number;
  },
) {
  const params = new URLSearchParams();
  params.set("q", q);
  if (opts?.source_id) params.set("source_id", opts.source_id);
  if (opts?.object_type) params.set("object_type", opts.object_type);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  return apiClient<{
    items: CatalogObject[];
    limit: number;
    offset: number;
    rank_mode: "vector" | "lexical";
    truncated: boolean;
  }>(`/catalog/objects/search?${params.toString()}`);
}

export function listSemanticsChanges(
  objectId: string,
  params?: SemanticsChangeQuery,
) {
  const qs = new URLSearchParams();
  if (params?.scope) qs.set("scope", params.scope);
  if (params?.column_id) qs.set("column_id", params.column_id);
  if (params?.field_name) qs.set("field_name", params.field_name);
  if (params?.semantic_source) qs.set("semantic_source", params.semantic_source);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<{
    items: SemanticsChange[];
    total: number;
    limit: number;
    offset: number;
  }>(`/objects/${encodeURIComponent(objectId)}/semantics-changes${suffix}`);
}
