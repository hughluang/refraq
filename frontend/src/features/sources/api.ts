import { apiClient } from "@/lib/api";
import type { Connection, Job, Source } from "@/features/sources/types";
import type { CatalogObject } from "@/features/sources/types";

export function listSources() {
  return apiClient<{ items: Source[] }>("/sources");
}

export function createSource(body: {
  key: string;
  name: string;
  kind: "database";
  description?: string | null;
  database_name: string;
  schema_filter?: string | null;
}) {
  return apiClient<{ source: Source }>("/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listConnections(sourceId: string) {
  return apiClient<{ items: Connection[] }>(
    `/sources/${sourceId}/connections`,
  );
}

export function createConnection(
  sourceId: string,
  body: {
    name: string;
    engine: "postgresql" | "mssql" | "oracle";
    host: string;
    port: number;
    secret: { username: string; password: string };
  },
) {
  return apiClient<{ connection: Connection }>(
    `/sources/${sourceId}/connections`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function patchConnection(
  connectionId: string,
  body: Partial<{
    name: string;
    engine: "postgresql" | "mssql" | "oracle";
    host: string;
    port: number;
    status: "active" | "disabled";
  }>,
) {
  return apiClient<{ connection: Connection }>(`/connections/${connectionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function rotateConnectionSecret(
  connectionId: string,
  secret: { username: string; password: string },
) {
  return apiClient<{ connection: Connection }>(
    `/connections/${connectionId}/secret`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret }),
    },
  );
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
