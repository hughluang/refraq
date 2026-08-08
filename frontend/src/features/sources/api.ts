import { apiClient } from "@/lib/api";
import type {
  ConnectorSpec,
  Engine,
  Job,
  Source,
  SourceAccess,
} from "@/features/sources/types";
import type {
  CatalogColumn,
  CatalogJoin,
  CatalogObject,
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

export function listCatalogObjects(sourceId: string, q?: string) {
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return apiClient<{ items: CatalogObject[] }>(
    `/sources/${sourceId}/objects${query}`,
  );
}

export function getCatalogObject(objectId: string) {
  return apiClient<{ object: CatalogObject }>(`/objects/${objectId}`);
}

export function patchObjectSemantics(
  objectId: string,
  body: {
    business_name?: string | null;
    business_description?: string | null;
  },
) {
  return apiClient<{ object: CatalogObject }>(`/objects/${objectId}/semantics`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchColumnSemantics(
  columnId: string,
  body: {
    business_name?: string | null;
    business_description?: string | null;
  },
) {
  return apiClient<{ column: CatalogColumn }>(`/columns/${columnId}/semantics`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listObjectJoins(objectId: string) {
  return apiClient<{ items: CatalogJoin[] }>(`/objects/${objectId}/joins`);
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
