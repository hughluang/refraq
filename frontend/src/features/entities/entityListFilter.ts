import type { EntityStatus } from "@/features/entities/publishStatus";

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
