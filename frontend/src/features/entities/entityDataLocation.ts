import { useSyncExternalStore } from "react";

import type { DataSort } from "./accessTypes";
import { EMPTY_DATA_QUERY, readDataQuery, writeDataQuery } from "./entityDataQuery";
import { acceptedPage } from "@/lib/pagination";

const locationChange = "entity-data-location";

function subscribe(callback: () => void) {
  window.addEventListener(locationChange, callback);
  window.addEventListener("popstate", callback);
  return () => {
    window.removeEventListener(locationChange, callback);
    window.removeEventListener("popstate", callback);
  };
}

export function useDataLocation() {
  return useSyncExternalStore(
    subscribe,
    () => window.location.search,
    () => null,
  );
}

export function updateDataLocation(update: (params: URLSearchParams) => void) {
  const url = new URL(window.location.href);
  update(url.searchParams);
  url.searchParams.set("tab", "data");
  if (url.href === window.location.href) return;
  window.history.replaceState(window.history.state, "", url);
  window.dispatchEvent(new Event(locationChange));
}

export function clearDataOptions(params: URLSearchParams) {
  writeDataQuery(params, EMPTY_DATA_QUERY);
  for (const key of ["dataSort", "dataDirection", "dataPage", "dataSize"]) params.delete(key);
}

export function readDataLocation(search: string) {
  const params = new URLSearchParams(search);
  const page = acceptedPage(params.get("dataPage") ?? "1");
  const size = Number(params.get("dataSize") ?? "50");
  const field = params.get("dataSort");
  const direction = params.get("dataDirection");
  const sort: DataSort | null =
    field && (direction === "asc" || direction === "desc") ? { field, direction } : null;
  const query = readDataQuery(params);
  const ambiguous = ["dataSort", "dataDirection", "dataPage", "dataSize"].some(
    (key) => params.getAll(key).length > 1,
  );
  const valid =
    !ambiguous &&
    page !== null &&
    Number.isSafeInteger(size) &&
    size > 0 &&
    ((field === null && direction === null) || sort !== null) &&
    query !== null;

  return { query, sort, page: page ?? 1, size, valid };
}

export function changeDataPage(page: number) {
  updateDataLocation((params) => {
    if (page === 1) params.delete("dataPage");
    else params.set("dataPage", String(page));
  });
}
