"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

export type ListFilterSpec =
  | { key: string; type: "select"; defaultValue: string }
  | { key: string; type: "multi"; defaultValue: readonly string[] };

export type UseListQueryOptions = {
  /** Query key for search. `false` omits search. Default key is `q`. */
  search?: string | false;
  filters?: readonly ListFilterSpec[];
  /** Default `page`. */
  pageKey?: string;
};

export type ListQuery = {
  searchEnabled: boolean;
  search: string;
  setSearch: (value: string) => void;
  filters: readonly ListFilterSpec[];
  select: (key: string) => string;
  multi: (key: string) => readonly string[];
  setFilter: (key: string, value: string | readonly string[]) => void;
  page: number;
  setPage: (page: number) => void;
  clear: () => void;
  /** Search or a filter differs from its default. Page is not a filter. */
  isFiltered: boolean;
};

const DEFAULT_SEARCH_KEY = "q";
const DEFAULT_PAGE_KEY = "page";
const NO_FILTERS: readonly ListFilterSpec[] = [];
type QueryState = {
  search: string;
  values: Record<string, string | readonly string[]>;
  page: number;
};

function canonical(values: readonly string[]): string {
  return [...values].sort().join("\0");
}

function isDefault(
  filter: ListFilterSpec,
  value: string | readonly string[] | undefined,
): boolean {
  if (filter.type === "select") return value === filter.defaultValue;
  if (!Array.isArray(value)) return false;
  return canonical(value) === canonical(filter.defaultValue);
}

function sameQuery(
  left: QueryState,
  right: QueryState,
  filters: readonly ListFilterSpec[],
): boolean {
  if (left.search !== right.search || left.page !== right.page) return false;
  return filters.every((filter) =>
    isDefault(filter, left.values[filter.key])
      ? isDefault(filter, right.values[filter.key])
      : sameFilter(filter, left.values[filter.key], right.values[filter.key]),
  );
}

function sameFilter(
  filter: ListFilterSpec,
  left: string | readonly string[] | undefined,
  right: string | readonly string[] | undefined,
): boolean {
  if (filter.type === "select") return left === right;
  if (!Array.isArray(left) || !Array.isArray(right)) return false;
  return canonical(left) === canonical(right);
}

function parsePage(raw: string | null): number {
  if (!raw) return 1;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) return 1;
  return value;
}

function readFilter(
  params: URLSearchParams,
  filter: ListFilterSpec,
): string | readonly string[] {
  if (!params.has(filter.key)) return filter.defaultValue;
  if (filter.type === "select") return params.get(filter.key) ?? "";
  return params.getAll(filter.key).filter((value) => value !== "");
}

function readState(
  params: URLSearchParams,
  searchKey: string | null,
  filters: readonly ListFilterSpec[],
  pageKey: string,
): QueryState {
  const values: Record<string, string | readonly string[]> = {};
  for (const filter of filters) {
    values[filter.key] = readFilter(params, filter);
  }
  return {
    search: searchKey ? (params.get(searchKey) ?? "").trim() : "",
    values,
    page: parsePage(params.get(pageKey)),
  };
}

function blankState(
  filters: readonly ListFilterSpec[],
): QueryState {
  const values: Record<string, string | readonly string[]> = {};
  for (const filter of filters) values[filter.key] = filter.defaultValue;
  return { search: "", values, page: 1 };
}

/**
 * An empty multi that is not the default is written as `key=` so a reload
 * does not fall back to the default set.
 */
function writeHref(
  locationHref: string,
  state: QueryState,
  searchKey: string | null,
  filters: readonly ListFilterSpec[],
  pageKey: string,
): string {
  const url = new URL(locationHref);
  if (searchKey) url.searchParams.delete(searchKey);
  for (const filter of filters) url.searchParams.delete(filter.key);
  url.searchParams.delete(pageKey);
  if (searchKey && state.search !== "") {
    url.searchParams.set(searchKey, state.search);
  }
  for (const filter of filters) {
    const value = state.values[filter.key];
    if (value === undefined || isDefault(filter, value)) continue;
    if (filter.type === "select") {
      url.searchParams.set(filter.key, String(value));
      continue;
    }
    const items = value as readonly string[];
    if (items.length === 0) {
      url.searchParams.append(filter.key, "");
      continue;
    }
    for (const item of items) url.searchParams.append(filter.key, item);
  }
  if (state.page > 1) url.searchParams.set(pageKey, String(state.page));
  return `${url.pathname}${url.search}${url.hash}`;
}

function specKeyOf(filters: readonly ListFilterSpec[]): string {
  return JSON.stringify(
    filters.map((filter) =>
      filter.type === "select"
        ? ["select", filter.key, filter.defaultValue]
        : ["multi", filter.key, canonical(filter.defaultValue)],
    ),
  );
}

function normalize(
  filter: ListFilterSpec,
  value: string | readonly string[],
): string | readonly string[] {
  if (filter.type === "select") {
    const text = typeof value === "string" ? value : "";
    return text === filter.defaultValue ? filter.defaultValue : text;
  }
  const items = Array.isArray(value) ? [...value] : [];
  return canonical(items) === canonical(filter.defaultValue)
    ? filter.defaultValue
    : items;
}

function filtered(
  state: QueryState,
  searchEnabled: boolean,
  filters: readonly ListFilterSpec[],
): boolean {
  if (searchEnabled && state.search !== "") return true;
  return filters.some((filter) => !isDefault(filter, state.values[filter.key]));
}

/**
 * List search, filters, and page. Reads `useSearchParams` and writes with
 * `history.replaceState` (no history entry). Defaults are omitted. A search
 * or filter change resets the page to 1.
 */
export function useListQuery(options: UseListQueryOptions = {}): ListQuery {
  const searchKey =
    options.search === false ? null : (options.search ?? DEFAULT_SEARCH_KEY);
  const pageKey = options.pageKey ?? DEFAULT_PAGE_KEY;
  const filters = options.filters ?? NO_FILTERS;
  const filtersKey = specKeyOf(filters);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const searchKeyRef = useRef(searchKey);
  searchKeyRef.current = searchKey;
  const pageKeyRef = useRef(pageKey);
  pageKeyRef.current = pageKey;

  const searchParams = useSearchParams();
  const external = searchParams.toString();
  const [state, setState] = useState<QueryState>(() =>
    readState(searchParams, searchKey, filters, pageKey),
  );
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const next = readState(
      new URLSearchParams(external),
      searchKeyRef.current,
      filtersRef.current,
      pageKeyRef.current,
    );
    setState((current) =>
      sameQuery(current, next, filtersRef.current) ? current : next,
    );
  }, [external, filtersKey]);

  const publish = useCallback((next: QueryState) => {
    if (sameQuery(stateRef.current, next, filtersRef.current)) return;
    stateRef.current = next;
    setState(next);
    const href = writeHref(
      window.location.href,
      next,
      searchKeyRef.current,
      filtersRef.current,
      pageKeyRef.current,
    );
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (href === current) return;
    window.history.replaceState(window.history.state, "", href);
  }, []);

  const setSearch = useCallback(
    (value: string) => {
      const search = value.trim();
      const current = stateRef.current;
      if (current.search === search) return;
      publish({ ...current, search, page: 1 });
    },
    [publish],
  );

  const setFilter = useCallback(
    (key: string, value: string | readonly string[]) => {
      const spec = filtersRef.current.find((item) => item.key === key) as ListFilterSpec;
      const normalized = normalize(spec, value);
      const current = stateRef.current;
      if (sameFilter(spec, current.values[key], normalized)) return;
      publish({
        ...current,
        page: 1,
        values: { ...current.values, [key]: normalized },
      });
    },
    [publish],
  );

  const setPage = useCallback(
    (page: number) => {
      const current = stateRef.current;
      if (current.page === page) return;
      publish({ ...current, page });
    },
    [publish],
  );

  const clear = useCallback(() => {
    publish(blankState(filtersRef.current));
  }, [publish]);

  const select = useCallback(
    (key: string) => state.values[key] as string,
    [state.values],
  );

  const multi = useCallback(
    (key: string) => state.values[key] as readonly string[],
    [state.values],
  );

  return {
    searchEnabled: searchKey !== null,
    search: state.search,
    setSearch,
    filters,
    select,
    multi,
    setFilter,
    page: state.page,
    setPage,
    clear,
    isFiltered: filtered(state, searchKey !== null, filters),
  };
}
