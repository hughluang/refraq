import { apiClient } from "@/lib/api";
import type { ScheduledTask } from "@/features/schedules/types";
import type { OffsetPage } from "@/lib/pagination";
import type {
  ConnectorSpec,
  Engine,
  Source,
  SourceAccess,
} from "@/features/sources/types";

export function listSources(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<OffsetPage<Source>>(`/sources${suffix}`);
}

export function getAccessSchema(engine: Engine) {
  return apiClient<{ engine: string; schema: ConnectorSpec }>(
    `/sources/access-schema/${engine}`,
  );
}

export function getSource(sourceId: string) {
  return apiClient<{ source: Source }>(`/sources/${sourceId}`);
}

export function getSourceAccess(sourceId: string) {
  return apiClient<{ access: SourceAccess }>(`/sources/${sourceId}/access`);
}

export function createSource(body: {
  key: string;
  name: string;
  kind: "database";
  description?: string | null;
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
    engine: Engine;
    access: SourceAccess;
  }>,
) {
  return apiClient<{ source: Source; schedules?: ScheduledTask[] }>(
    `/sources/${sourceId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
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
