"use client";

import { useDebouncedValue } from "@mantine/hooks";

export const SEARCH_DEBOUNCE_MS = 300;

export function useSearchDebounce<T>(value: T): T {
  const [debounced] = useDebouncedValue(value, SEARCH_DEBOUNCE_MS);
  if (value === "" || value == null) return value;
  return debounced;
}
