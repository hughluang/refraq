import { apiClient } from "@/lib/api";
import type {
  CatalogColumn,
  CatalogObject,
} from "@/features/sources/types";

export function listCatalogObjects(
  sourceId: string,
  q?: string,
  opts?: {
    limit?: number;
    offset?: number;
    object_type?: string;
    include_absent?: boolean;
    business_semantics_ready?: boolean;
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
    params.set(
      "business_semantics_ready",
      String(opts.business_semantics_ready),
    );
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiClient<{
    items: CatalogObject[];
    total: number;
    limit: number;
    offset: number;
  }>(`/sources/${sourceId}/objects${query}`);
}

export function searchCatalogColumns(params: {
  q: string;
  source_id?: string;
  object_type?: string;
  limit?: number;
  offset?: number;
}) {
  const qs = new URLSearchParams();
  qs.set("q", params.q);
  if (params.source_id) qs.set("source_id", params.source_id);
  if (params.object_type) qs.set("object_type", params.object_type);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  return apiClient<{
    items: CatalogColumn[];
    total: number;
    limit: number;
    offset: number;
  }>(`/catalog/columns/search?${qs.toString()}`);
}

export function getCatalogObject(objectId: string) {
  return apiClient<{ object: CatalogObject }>(`/objects/${objectId}`);
}
