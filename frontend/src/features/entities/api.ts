import { apiClient } from "@/lib/api";

import type { EntityStatus } from "@/features/entities/publishStatus";

import type {
  BusinessEntity,
  ChangeLogEntryDetail,
  ChangeLogPage,
  EntityCreate,
  EntityJobEnqueue,
  EntityPatch,
  EntityTag,
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
  tag_id?: readonly string[];
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}) {
  const { signal, ...query } = params ?? {};
  return apiClient<OffsetPage<BusinessEntity>>(`/entities${querySuffix(query)}`, {
    signal,
  });
}

export function createEntity(body: EntityCreate) {
  return apiClient<{ entity: BusinessEntity }>("/entities", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getEntity(id: string, init?: { signal?: AbortSignal }) {
  return apiClient<{ entity: BusinessEntity }>(`/entities/${id}`, {
    signal: init?.signal,
  });
}

export function listEntityChangeLog(
  entityId: string,
  params?: {
    before_sequence?: number;
    operation?: string;
    source?: string;
    subject?: string;
    row_identity?: string;
    occurred_from?: string;
    occurred_to?: string;
    signal?: AbortSignal;
  },
) {
  const { signal, ...query } = params ?? {};
  return apiClient<ChangeLogPage>(
    `/entities/${entityId}/change-log${querySuffix(query)}`,
    { signal },
  );
}

export function getEntityChangeLogEntry(
  entityId: string,
  sequence: number,
  init?: { signal?: AbortSignal },
) {
  return apiClient<ChangeLogEntryDetail>(
    `/entities/${entityId}/change-log/${sequence}`,
    { signal: init?.signal },
  );
}

export function patchEntity(id: string, body: EntityPatch) {
  return apiClient<{ entity: BusinessEntity }>(`/entities/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function addEntityTags(body: { entity_ids: string[]; tag_ids: string[] }) {
  return apiClient<{ subjects: { id: string; tags: EntityTag[]; tag_revision: number }[] }>(
    "/entities/tags/add",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function removeEntityTags(body: { entity_ids: string[]; tag_ids: string[] }) {
  return apiClient<{ subjects: { id: string; tags: EntityTag[]; tag_revision: number }[] }>(
    "/entities/tags/remove",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function replaceEntityTags(
  id: string,
  body: { base_revision: number; tag_ids: string[]; names: string[] },
) {
  return apiClient<{ tags: EntityTag[]; tag_revision: number }>(
    `/entities/${id}/tags`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
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

export type IncompatibleWriteNode = {
  channel_id: string;
  channel_name: string;
  node_id: string;
  node_name: string;
  on_incompatible_head: string;
  reasons: string[];
};

export type ChangeLogPublishEffect = "delete_all" | "delete_expired" | "none";

export function previewEntityPublish(entityId: string, versionId: string) {
  return apiClient<{
    incompatible_write_nodes: IncompatibleWriteNode[];
    change_log_effect: ChangeLogPublishEffect;
  }>(`/entities/${entityId}/versions/${versionId}/publish/preview`, {
    method: "POST",
  });
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
