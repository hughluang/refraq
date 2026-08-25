import { ApiError } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";
import { pageToOffset } from "@/lib/pagination";

export type PagedListFetch<T> = (
  query: PageQuery,
) => OffsetPage<T> | Promise<OffsetPage<T>>;

export type PagedListLoadResult<T> =
  | { kind: "stale" }
  | { kind: "disabled" }
  | { kind: "ok"; page: OffsetPage<T> }
  | { kind: "error"; message: string; requestId: string | null };

export function listErrorMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail : String(err);
}

export function listErrorRequestId(err: unknown): string | null {
  return err instanceof ApiError ? err.requestId : null;
}

/** Map a reset-key change onto the page that the next fetch should use. */
export function syncResetPage(args: {
  resetKey: string;
  previousKey: string;
  page: number;
}): { fetchPage: number; shouldSetPage: boolean } {
  if (args.resetKey === args.previousKey) {
    return { fetchPage: args.page, shouldSetPage: false };
  }
  return { fetchPage: 1, shouldSetPage: args.page !== 1 };
}

export function isPromiseLike<T>(
  value: T | Promise<T>,
): value is Promise<T> {
  return typeof (value as Promise<T>).then === "function";
}

function finishLoad<T>(
  started: number,
  currentGeneration: () => number,
  page: OffsetPage<T>,
): PagedListLoadResult<T> {
  if (started !== currentGeneration()) return { kind: "stale" };
  return { kind: "ok", page };
}

function finishError(
  started: number,
  currentGeneration: () => number,
  err: unknown,
): PagedListLoadResult<never> {
  if (started !== currentGeneration()) return { kind: "stale" };
  return {
    kind: "error",
    message: listErrorMessage(err),
    requestId: listErrorRequestId(err),
  };
}

/**
 * One generation of a paged fetch. Callers discard `stale` results.
 * A synchronous `fetch` returns a result immediately so a local Offset Page
 * adapter can settle in the same layout pass.
 */
export function loadPagedGeneration<T>(args: {
  started: number;
  currentGeneration: () => number;
  enabled: boolean;
  fetch: PagedListFetch<T>;
  page: number;
  pageSize: number;
}): PagedListLoadResult<T> | Promise<PagedListLoadResult<T>> {
  if (!args.enabled) {
    if (args.started !== args.currentGeneration()) return { kind: "stale" };
    return { kind: "disabled" };
  }
  try {
    const data = args.fetch({
      limit: args.pageSize,
      offset: pageToOffset(args.page, args.pageSize),
    });
    if (isPromiseLike(data)) {
      return data.then(
        (page) => finishLoad(args.started, args.currentGeneration, page),
        (err: unknown) => finishError(args.started, args.currentGeneration, err),
      );
    }
    return finishLoad(args.started, args.currentGeneration, data);
  } catch (err) {
    return finishError(args.started, args.currentGeneration, err);
  }
}
