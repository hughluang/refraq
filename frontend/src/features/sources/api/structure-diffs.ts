import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";
import type { StructureDiff } from "@/features/sources/types";

export function listStructureDiffs(
  sourceId: string,
  params?: { limit?: number; offset?: number },
) {
  const q = new URLSearchParams();
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiClient<OffsetPage<StructureDiff>>(
    `/sources/${sourceId}/structure-diffs${suffix}`,
  );
}

export function getStructureDiff(diffId: string) {
  return apiClient<{ structure_diff: StructureDiff }>(
    `/structure-diffs/${diffId}`,
  );
}
