import { apiClient } from "@/lib/api";
import type {
  CatalogColumn,
  CatalogJoin,
  CatalogObject,
  ColumnSemanticsBatchItem,
  ColumnSemanticsPatch,
  ConnectorSpec,
  Engine,
  Job,
  JoinPathResult,
  ObjectSemanticsPatch,
  QueryResult,
  SampleRequestBody,
  SampleResult,
  Source,
  SourceAccess,
} from "@/features/sources/types";

export function listSources() {
  return apiClient<{ items: Source[] }>("/sources");
}

export function getAccessSchema(engine: Engine) {
  return apiClient<{ engine: string; schema: ConnectorSpec }>(
    `/sources/access-schema/${engine}`,
  );
}

export function getSourceAccess(sourceId: string) {
  return apiClient<{ access: SourceAccess }>(`/sources/${sourceId}/access`);
}

export function createSource(body: {
  key: string;
  name: string;
  kind: "database";
  description?: string | null;
  database_name: string;
  schema_filter?: string | null;
  engine: Engine;
  access: SourceAccess;
}) {
  return apiClient<{ source: Source }>("/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchSource(
  sourceId: string,
  body: Partial<{
    name: string;
    description: string | null;
    status: "active" | "disabled";
    database_name: string;
    schema_filter: string | null;
    engine: Engine;
    access: SourceAccess;
  }>,
) {
  return apiClient<{ source: Source }>(`/sources/${sourceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteSource(sourceId: string) {
  return apiClient<void>(`/sources/${sourceId}`, { method: "DELETE" });
}

export type SourceTestResult = {
  ok: boolean;
  code?: string | null;
  message?: string | null;
};

export function testSourceDraft(body: {
  engine: Engine;
  access: SourceAccess;
  database_name: string;
}) {
  return apiClient<SourceTestResult>("/sources/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function testSource(
  sourceId: string,
  body: {
    database_name: string;
    engine?: Engine;
    access?: SourceAccess;
  },
) {
  return apiClient<SourceTestResult>(`/sources/${sourceId}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listCatalogObjects(
  sourceId: string,
  q?: string,
  opts?: {
    limit?: number;
    offset?: number;
    object_type?: string;
    include_absent?: boolean;
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
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiClient<{
    items: CatalogObject[];
    total: number;
    limit: number;
    offset: number;
  }>(`/sources/${sourceId}/objects${query}`);
}

export function searchCatalogObjects(params: {
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
    items: CatalogObject[];
    total: number;
    limit: number;
    offset: number;
  }>(`/catalog/objects/search?${qs.toString()}`);
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

export function patchColumnSemantics(
  columnId: string,
  body: ColumnSemanticsPatch,
) {
  return apiClient<{ column: CatalogColumn }>(`/columns/${columnId}/semantics`, {
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

export function listObjectJoins(objectId: string) {
  return apiClient<{ items: CatalogJoin[] }>(`/objects/${objectId}/joins`);
}

export function upsertJoin(body: {
  from_column_id: string;
  to_column_id: string;
  evidence: string;
  join_kind?: string;
  join_expression?: string | null;
}) {
  return apiClient<{ join: CatalogJoin }>("/joins", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteJoin(joinId: string) {
  return apiClient<void>(`/joins/${joinId}`, { method: "DELETE" });
}

export function getJoinPath(params: {
  start: string;
  target?: string;
  max_hops?: number;
  top_targets?: number;
}) {
  const qs = new URLSearchParams();
  qs.set("start", params.start);
  if (params.target) qs.set("target", params.target);
  if (params.max_hops != null) qs.set("max_hops", String(params.max_hops));
  if (params.top_targets != null) {
    qs.set("top_targets", String(params.top_targets));
  }
  return apiClient<JoinPathResult>(`/joins/path?${qs.toString()}`);
}

export function runSourceQuery(
  sourceId: string,
  body: { sql: string; max_rows?: number },
) {
  return apiClient<QueryResult>(`/sources/${sourceId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function runObjectSample(objectId: string, body: SampleRequestBody) {
  return apiClient<SampleResult>(`/objects/${objectId}/sample`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listSourceJobs(sourceId: string) {
  return apiClient<{ items: Job[] }>(`/sources/${sourceId}/jobs`);
}

export function enqueueStructureJob(sourceId: string) {
  return apiClient<{ job: Job }>(`/sources/${sourceId}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "structure" }),
  });
}

export function cancelJob(jobId: string) {
  return apiClient<{ job: Job }>(`/jobs/${jobId}/cancel`, { method: "POST" });
}
