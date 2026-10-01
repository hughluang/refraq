export type DictionaryListStatus = "available" | "deprecated";

export const DEFAULT_DICTIONARY_LIST_STATUSES = [
  "available",
] as const satisfies readonly DictionaryListStatus[];

/**
 * The opening selection is the default. A search term or any other status
 * set is a filter that is off that default.
 */
export function dictionaryListIsFiltered(
  q: string,
  statuses: readonly string[],
): boolean {
  if (q.trim() !== "") return true;
  if (statuses.length !== DEFAULT_DICTIONARY_LIST_STATUSES.length) return true;
  const selected = new Set(statuses);
  return DEFAULT_DICTIONARY_LIST_STATUSES.some((status) => !selected.has(status));
}
