"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

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
  onError?: (message: string) => void;
};

export type UsePagedListResult<T> = {
  items: T[];
  total: number;
  page: number;
  setPage: (page: number) => void;
  loading: boolean;
  error: string | null;
  errorRequestId: string | null;
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
}: UsePagedListOptions<T>): UsePagedListResult<T> {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(initialLoading);
  const [error, setError] = useState<string | null>(null);
  const [errorRequestId, setErrorRequestId] = useState<string | null>(null);
  const generationRef = useRef(0);
  const resetKey = JSON.stringify(resetDeps);
  const resetKeyRef = useRef(resetKey);
  const reset = syncResetPage({
    resetKey,
    previousKey: resetKeyRef.current,
    page,
  });
  if (resetKeyRef.current !== resetKey) {
    resetKeyRef.current = resetKey;
    if (reset.shouldSetPage) {
      setPage(1);
    }
  }
  const fetchPage = reset.fetchPage;

  const applyResult = useCallback(
    (result: PagedListLoadResult<T>) => {
      if (result.kind === "stale") return;
      if (result.kind === "disabled") {
        setItems([]);
        setTotal(0);
        setError(null);
        setErrorRequestId(null);
        setLoading(false);
        return;
      }
      if (result.kind === "ok") {
        setItems(result.page.items);
        setTotal(result.page.total);
        setError(null);
        setErrorRequestId(null);
        setLoading(false);
        return;
      }
      setError(result.message);
      setErrorRequestId(result.requestId);
      onError?.(result.message);
      setLoading(false);
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
    void load();
  }, [load]);

  return {
    items,
    total,
    page: fetchPage,
    setPage,
    loading,
    error,
    errorRequestId,
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
