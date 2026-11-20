"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import type { ListPresentation } from "@/lib/list-state";
import { listPresentationOf } from "@/lib/list-state";
import {
  isPromiseLike,
  loadPagedGeneration,
  syncResetPage,
  type PagedListFetch,
  type PagedListLoadResult,
} from "@/lib/paged-list-session";

export type UsePagedListOptions<T> = {
  pageSize: number;
  fetch: PagedListFetch<T>;
  resetDeps?: readonly unknown[];
  enabled?: boolean;
  filtered?: boolean;
  /** First paint is a skeleton unless this is false (local Offset Page adapters). */
  initialLoading?: boolean;
  onError?: (error: unknown) => void;
  /**
   * URL page from `useListQuery`. With `onPageChange`, the pager writes that
   * page; omitted, the page stays inside the hook.
   */
  page?: number;
  onPageChange?: (page: number) => void;
};

export type UsePagedListResult<T> = {
  items: T[];
  total: number;
  page: number;
  setPage: (page: number) => void;
  loading: boolean;
  error: string | null;
  errorRequestId: string | null;
  accessDenied: boolean;
  reload: () => Promise<void>;
  pageSize: number;
  presentation: ListPresentation;
};

export function usePagedList<T>({
  pageSize,
  fetch,
  resetDeps = [],
  enabled = true,
  filtered = false,
  initialLoading = true,
  onError,
  page: pageProp,
  onPageChange,
}: UsePagedListOptions<T>): UsePagedListResult<T> {
  const [internalPage, setInternalPage] = useState(1);
  const controlled = pageProp !== undefined;
  const onPageChangeRef = useRef(onPageChange);
  onPageChangeRef.current = onPageChange;
  const heldPage = useRef<number | null>(null);
  if (controlled && heldPage.current != null && pageProp === heldPage.current) {
    heldPage.current = null;
  }
  const page = heldPage.current ?? (controlled ? pageProp : internalPage);
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(initialLoading);
  const [failure, setFailure] = useState<{ message: string; requestId: string | null; accessDenied: boolean } | null>(null);
  const error = failure?.message ?? null;
  const generationRef = useRef(0);
  const resetKey = JSON.stringify(resetDeps);
  const resetKeyRef = useRef(resetKey);
  const reset = syncResetPage({
    resetKey,
    previousKey: resetKeyRef.current,
    page,
  });
  const resetNotice = controlled && reset.shouldSetPage;
  if (resetKeyRef.current !== resetKey) {
    resetKeyRef.current = resetKey;
    if (reset.shouldSetPage && !controlled) {
      setInternalPage(1);
    }
    if (reset.shouldSetPage && controlled) {
      heldPage.current = 1;
    }
  }
  const fetchPage = reset.fetchPage;

  const applyResult = useCallback(
    (result: PagedListLoadResult<T>) => {
      if (result.kind === "stale") return;
      setLoading(false);
      if (result.kind !== "error") {
        setFailure(null);
        setItems(result.kind === "ok" ? result.page.items : []);
        setTotal(result.kind === "ok" ? result.page.total : 0);
        return;
      }
      const accessDenied = result.error instanceof ApiError && [403, 404].includes(result.error.status);
      setFailure({ message: result.message, requestId: result.requestId, accessDenied });
      if (accessDenied) {
        setItems([]);
        setTotal(0);
      }
      onError?.(result.error);
    },
    [onError],
  );

  // resetKey must be a load dependency: syncResetPage keeps fetchPage at 1 when
  // already on page 1, so a stable fetch alone would not rebuild load.
  const load = useCallback(async () => {
    const started = ++generationRef.current;
    if (enabled) {
      setLoading(true);
    }
    const pending = loadPagedGeneration({
      started,
      currentGeneration: () => generationRef.current,
      enabled,
      fetch,
      page: fetchPage,
      pageSize,
    });
    if (isPromiseLike(pending)) {
      applyResult(await pending);
      return;
    }
    applyResult(pending);
  }, [applyResult, enabled, fetch, fetchPage, pageSize, resetKey]);

  useLayoutEffect(() => {
    if (!resetNotice) return;
    onPageChangeRef.current?.(1);
  }, [resetNotice, resetKey]);

  useLayoutEffect(() => {
    void load();
  }, [load]);

  const setPage = useCallback(
    (next: number) => {
      if (controlled) {
        onPageChangeRef.current?.(next);
        return;
      }
      setInternalPage(next);
    },
    [controlled],
  );

  return {
    items,
    total,
    page: fetchPage,
    setPage,
    loading,
    error,
    errorRequestId: failure?.requestId ?? null,
    accessDenied: failure?.accessDenied ?? false,
    reload: load,
    pageSize,
    presentation: listPresentationOf({
      loading,
      error,
      total,
      itemCount: items.length,
      filtered,
    }),
  };
}
