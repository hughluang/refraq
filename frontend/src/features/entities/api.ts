import { apiClient } from "@/lib/api";

import type { EntityStatus } from "@/features/entities/publishStatus";

import type {
  BusinessEntity,
  EntityCreate,
  EntityJobEnqueue,
  EntityPatch,
  EntityVersion,
  ShapeWrite,
} from "./types";

export type OffsetPage<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

function querySuffix(
  params?: Record<string, string | number | readonly string[] | undefined>,
) {
  const qs = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item !== "") qs.append(key, item);
        }
        continue;
      }
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export function listEntities(params?: {
  q?: string;
  status?: readonly EntityStatus[];
  limit?: number;
  offset?: number;
}) {
  return apiClient<OffsetPage<BusinessEntity>>(
    `/entities${querySuffix(params)}`,
  );
}

export function createEntity(body: EntityCreate) {
  return apiClient<{ entity: BusinessEntity }>("/entities", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getEntity(id: string) {
  return apiClient<{ entity: BusinessEntity }>(`/entities/${id}`);
}

export function patchEntity(id: string, body: EntityPatch) {
  return apiClient<{ entity: BusinessEntity }>(`/entities/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteEntity(id: string) {
  return apiClient<void>(`/entities/${id}`, { method: "DELETE" });
}

export function listVersions(
  entityId: string,
  params?: { limit?: number; offset?: number },
) {
  return apiClient<OffsetPage<EntityVersion>>(
    `/entities/${entityId}/versions${querySuffix(params)}`,
  );
}

export function openVersion(entityId: string, body: ShapeWrite) {
  return apiClient<{ version: EntityVersion }>(
    `/entities/${entityId}/versions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function getVersion(entityId: string, versionId: string) {
  return apiClient<{ version: EntityVersion }>(
    `/entities/${entityId}/versions/${versionId}`,
  );
}

export function publishVersion(entityId: string, versionId: string) {
  return apiClient<EntityJobEnqueue>(
    `/entities/${entityId}/versions/${versionId}/publish`,
    { method: "POST" },
  );
}

export function deprecateEntity(entityId: string) {
  return apiClient<{ entity: BusinessEntity }>(
    `/entities/${entityId}/deprecate`,
    { method: "POST" },
  );
}

export function enqueueDropTable(entityId: string, versionId: string) {
  return apiClient<EntityJobEnqueue>(
    `/entities/${entityId}/versions/${versionId}/drop-table`,
    { method: "POST" },
  );
}
