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
 * The opening selection is the default. A search term or any other status
 * set is a filter that is off that default.
 */
export function entityListIsFiltered(
  q: string,
  statuses: readonly string[],
): boolean {
  if (q.trim() !== "") return true;
  if (statuses.length !== DEFAULT_ENTITY_LIST_STATUSES.length) return true;
  const selected = new Set(statuses);
  return DEFAULT_ENTITY_LIST_STATUSES.some((status) => !selected.has(status));
}

export function entityListStatuses(values: readonly string[]): EntityStatus[] {
  return values.filter((value): value is EntityStatus =>
    ENTITY_LIST_STATUS_SET.has(value),
  );
}
