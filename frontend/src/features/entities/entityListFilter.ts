import type { EntityStatus } from "@/features/entities/publishStatus";
import { apiClient } from "@/lib/api";

export const DEFAULT_ENTITY_LIST_STATUSES = [
  "not_serving",
  "serving",
] as const satisfies readonly EntityStatus[];

const ENTITY_LIST_STATUS_SET = new Set<string>([
  ...DEFAULT_ENTITY_LIST_STATUSES,
  "deprecated",
]);

/** Empty selection matches nothing, so the list must not call the API. */
export function entityListShouldFetch(statuses: readonly string[]): boolean {
  return statuses.length > 0;
}

/**
 * The opening selection is the default. A search term, a Tag, or any other
 * status set is a filter that is off that default.
 */
export function entityListIsFiltered(
  q: string,
  statuses: readonly string[],
  tagIds: readonly string[] = [],
): boolean {
  if (q.trim() !== "") return true;
  if (tagIds.some((id) => id !== "")) return true;
  if (statuses.length !== DEFAULT_ENTITY_LIST_STATUSES.length) return true;
  const selected = new Set(statuses);
  return DEFAULT_ENTITY_LIST_STATUSES.some((status) => !selected.has(status));
}

export type EntityListRequest = {
  q?: string;
  status: EntityStatus[];
  tag_id?: string[];
  limit: number;
  offset: number;
};

/** Query the list sends. Null means the empty status selection must not fetch. */
export function entityListRequest(input: {
  q: string;
  statuses: readonly string[];
  tagIds: readonly string[];
  limit: number;
  offset: number;
}): EntityListRequest | null {
  const status = entityListStatuses(input.statuses);
  if (!entityListShouldFetch(status)) return null;
  const request: EntityListRequest = {
    status,
    limit: input.limit,
    offset: input.offset,
  };
  const q = input.q.trim();
  if (q !== "") request.q = q;
  const tagIds = input.tagIds.filter((id) => id !== "");
  if (tagIds.length > 0) request.tag_id = [...tagIds];
  return request;
}

export function entityListStatuses(values: readonly string[]): EntityStatus[] {
  return values.filter((value): value is EntityStatus =>
    ENTITY_LIST_STATUS_SET.has(value),
  );
}

export type EntitySavedQuery = {
  q: string;
  status: EntityStatus[];
  tag_ids: string[];
};

export type StoredEntityFilter = {
  id: string;
  query: EntitySavedQuery;
};

function collapse<T>(values: readonly T[]): T[] {
  const seen: T[] = [];
  for (const item of values) {
    if (!seen.includes(item)) seen.push(item);
  }
  return seen;
}

function sameValues(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  const orderedLeft = [...left].sort();
  const orderedRight = [...right].sort();
  return orderedLeft.every((item, index) => item === orderedRight[index]);
}

/** Query stored on a Saved Filter. Offset is a page, not part of the filter. */
export function entitySavedQuery(input: {
  q: string;
  statuses: readonly string[];
  tagIds: readonly string[];
}): EntitySavedQuery {
  return {
    q: input.q.trim(),
    status: collapse(entityListStatuses(input.statuses)),
    tag_ids: collapse(input.tagIds.filter((id) => id !== "")),
  };
}

export function sameEntitySavedQuery(
  left: EntitySavedQuery,
  right: EntitySavedQuery,
): boolean {
  return (
    left.q === right.q &&
    sameValues(left.status, right.status) &&
    sameValues(left.tag_ids, right.tag_ids)
  );
}

/**
 * The filter an explicit save writes. The filter this visit applied wins,
 * then one whose stored query equals the current controls. A shared link
 * that matches nothing creates a filter.
 */
export function entitySaveTarget(input: {
  appliedId: string | null;
  stored: readonly StoredEntityFilter[];
  current: EntitySavedQuery;
}): { kind: "update"; id: string } | { kind: "create" } {
  if (input.appliedId) return { kind: "update", id: input.appliedId };
  const match = input.stored.find((item) =>
    sameEntitySavedQuery(item.query, input.current),
  );
  if (match) return { kind: "update", id: match.id };
  return { kind: "create" };
}

export type EntitySavedFilter = {
  id: string;
  name: string;
  query: EntitySavedQuery;
};

type EntitySavedFilterWire = EntitySavedFilter & {
  list: string;
  created_at: string;
  updated_at: string;
};

function asEntityFilter(record: EntitySavedFilterWire): EntitySavedFilter {
  return { id: record.id, name: record.name, query: record.query };
}

/** The caller's Entity filters and the one remembered for the next visit. */
export async function loadEntitySavedFilters(): Promise<{
  filters: EntitySavedFilter[];
  rememberedId: string | null;
}> {
  const [page, memory] = await Promise.all([
    apiClient<{ items: EntitySavedFilterWire[] }>(
      "/saved-filters?list=entities&limit=50",
    ),
    apiClient<{ saved_filter_id: string | null }>(
      "/saved-filters/default?list=entities",
    ),
  ]);
  const filters = page.items.map(asEntityFilter);
  const rememberedId = filters.some((item) => item.id === memory.saved_filter_id)
    ? memory.saved_filter_id
    : null;
  return { filters, rememberedId };
}

export function createEntitySavedFilter(name: string, query: EntitySavedQuery) {
  return apiClient<{ saved_filter: EntitySavedFilterWire }>("/saved-filters", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ list: "entities", name, query }),
  });
}

export function patchEntitySavedFilter(
  id: string,
  body: { name?: string; query: EntitySavedQuery },
) {
  return apiClient<{ saved_filter: EntitySavedFilterWire }>(
    `/saved-filters/${id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function rememberEntitySavedFilter(id: string | null) {
  return apiClient<{ saved_filter_id: string | null }>("/saved-filters/default", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ list: "entities", saved_filter_id: id }),
  });
}
