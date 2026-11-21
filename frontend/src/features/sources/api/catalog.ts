import { apiClient } from "@/lib/api";
import type { Mirror } from "@/features/mirrors/types";
import type { CatalogObject, SemanticsChange } from "@/features/sources/types";
import type { OffsetPage } from "@/lib/pagination";

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

export function getCatalogObject(objectId: string, signal?: AbortSignal) {
  return apiClient<{ object: CatalogObject }>(`/objects/${encodeURIComponent(objectId)}`, { signal });
}

export function enableCatalogMirror(objectId: string, signal: AbortSignal) {
  return apiClient<{ mirror: Mirror; operation_id: string }>(
    `/objects/${encodeURIComponent(objectId)}/mirror`,
    { method: "POST", signal },
  );
}

export async function resolveCatalogObject(objectRef: string, signal?: AbortSignal): Promise<{ object: CatalogObject | null }> {
  if (!objectRef.startsWith("obj/")) return getCatalogObject(objectRef, signal);
  const parts = objectRef.split("/");
  if (parts.length !== 6 || parts.some((part) => !part)) return { object: null };
  const [, engine, sourceKey, , objectType, name] = parts;
  const pageSize = 100;
  let sourceTotal = Infinity;
  for (let offset = 0; offset < sourceTotal; offset += pageSize) {
    const page = await listCatalogSources({ q: sourceKey, limit: pageSize, offset, signal });
    if (offset === 0) sourceTotal = page.total;
    const source = page.items.find((item) => item.key === sourceKey && item.engine === engine);
    if (source) {
      let objectTotal = Infinity;
      for (let objectOffset = 0; objectOffset < objectTotal; objectOffset += pageSize) {
        const objects = await listCatalogObjects(source.id, decodeURIComponent(name), {
          object_type: objectType, include_absent: true,
          limit: pageSize, offset: objectOffset, signal,
        });
        if (objectOffset === 0) objectTotal = objects.total;
        const exact = objects.items.find((item) => item.locator_key === objectRef);
        if (exact) return getCatalogObject(exact.id, signal);
        if (objects.items.length === 0) break;
      }
      return { object: null };
    }
    if (page.items.length === 0) break;
  }
  return { object: null };
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
  params?: { limit?: number; offset?: number },
) {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<{
    items: SemanticsChange[];
    total: number;
    limit: number;
    offset: number;
  }>(`/objects/${objectId}/semantics-changes${suffix}`);
}
