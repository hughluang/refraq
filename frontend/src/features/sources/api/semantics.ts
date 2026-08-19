import { apiClient } from "@/lib/api";
import type {
  CatalogObject,
  ColumnSemanticsBatchItem,
  ObjectSemanticsPatch,
} from "@/features/sources/types";

export function patchObjectSemantics(
  objectId: string,
  body: ObjectSemanticsPatch,
) {
  return apiClient<{ object: CatalogObject }>(`/objects/${objectId}/semantics`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchColumnSemanticsBatch(
  objectId: string,
  columns: ColumnSemanticsBatchItem[],
) {
  return apiClient<{
    object: CatalogObject;
    updated_count: number;
    requested_count: number;
    skipped_columns: Array<{ column_name?: string | null; reason: string }>;
  }>(`/objects/${objectId}/columns/semantics`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ columns }),
  });
}
