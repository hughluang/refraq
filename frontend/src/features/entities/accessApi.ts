import type {
  AccessGrant,
  AccessLadder,
  AccessProfile,
  AccessRestriction,
  AccessSummary,
  DataSchema,
} from "@/features/entities/accessTypes";
import { apiClient } from "@/lib/api";

export function getAccessSummary(entityId: string) {
  return apiClient<AccessSummary>(`/entities/${entityId}/access`);
}

export function putLadder(
  entityId: string,
  attributeId: string,
  levels: AccessLadder["levels"],
) {
  return apiClient<{ ladder: AccessLadder; policy_revision: number }>(
    `/entities/${entityId}/access/ladders/${attributeId}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ levels }),
    },
  );
}

export function createProfile(
  entityId: string,
  body: {
    key: string;
    name: string;
    description?: string | null;
    columns: { attribute_id: string; level: string }[];
  },
) {
  return apiClient<{ profile: AccessProfile; policy_revision: number }>(
    `/entities/${entityId}/access/profiles`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function patchProfile(
  entityId: string,
  profileId: string,
  body: {
    name?: string;
    description?: string | null;
    columns?: { attribute_id: string; level: string }[];
  },
) {
  return apiClient<{ profile: AccessProfile; policy_revision: number }>(
    `/entities/${entityId}/access/profiles/${profileId}`,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteProfile(entityId: string, profileId: string) {
  return apiClient<void>(`/entities/${entityId}/access/profiles/${profileId}`, {
    method: "DELETE",
  });
}

export function copyProfile(
  entityId: string,
  body: { source_entity_id: string; source_profile_id: string; key: string; name: string },
) {
  return apiClient<{
    profile: AccessProfile;
    dropped_columns: { attribute_name: string; reason: string }[];
    policy_revision: number;
  }>(`/entities/${entityId}/access/profiles/copy`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function createGrant(
  entityId: string,
  body: {
    subject: { type: string; id: string };
    profile_id: string;
    row_rule: Record<string, unknown> | null;
    actions: string[];
    status?: string;
    valid_until?: string | null;
  },
) {
  return apiClient<{ grant: AccessGrant; policy_revision: number }>(
    `/entities/${entityId}/access/grants`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteGrant(entityId: string, grantId: string) {
  return apiClient<void>(`/entities/${entityId}/access/grants/${grantId}`, {
    method: "DELETE",
  });
}

export function createRestriction(
  entityId: string,
  body: {
    applies_to: { mode: string; subjects?: { type: string; id: string }[] };
    row_rule: Record<string, unknown> | null;
    deny_columns: string[];
    ceilings: { attribute_id: string; level: string }[];
    actions: string[];
  },
) {
  return apiClient<{ restriction: AccessRestriction; policy_revision: number }>(
    `/entities/${entityId}/access/restrictions`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteRestriction(entityId: string, restrictionId: string) {
  return apiClient<void>(
    `/entities/${entityId}/access/restrictions/${restrictionId}`,
    { method: "DELETE" },
  );
}

export function previewAccess(
  entityId: string,
  body: {
    subject: { type: "user"; id: string };
    include_rows: boolean;
    limit?: number;
    offset?: number;
  },
) {
  return apiClient<{
    policy_revision: number;
    effective_grants: string[];
    schema: {
      attributes: {
        name: string;
        presentation?: { row_varying?: boolean; may_be_withheld?: boolean };
      }[];
      withheld_field: string | null;
    };
    rows: {
      items: Record<string, unknown>[];
      total: number;
    } | null;
  }>(`/entities/${entityId}/access/preview`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function loadDataSchema(tableName: string, body: Record<string, unknown>) {
  return apiClient<DataSchema>(`/entities/${tableName}/schema`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function queryDataRows(tableName: string, body: Record<string, unknown>) {
  return apiClient<{
    items: Record<string, unknown>[];
    total: number;
    limit: number;
    offset: number;
  }>(`/entities/${tableName}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
