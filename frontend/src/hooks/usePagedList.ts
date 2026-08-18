"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";
import { pageToOffset } from "@/lib/pagination";

export type UsePagedListOptions<T> = {
  pageSize: number;
  fetch: (query: PageQuery) => Promise<OffsetPage<T>>;
  resetDeps?: readonly unknown[];
  enabled?: boolean;
  onError?: (message: string) => void;
};

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.detail : String(err);
}

export function usePagedList<T>({
  pageSize,
  fetch,
  resetDeps = [],
  enabled = true,
  onError,
}: UsePagedListOptions<T>) {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const resetKey = JSON.stringify(resetDeps);
  const resetKeyRef = useRef(resetKey);
  const fetchPage = resetKeyRef.current === resetKey ? page : 1;
  if (resetKeyRef.current !== resetKey) {
    resetKeyRef.current = resetKey;
    if (page !== 1) {
      setPage(1);
    }
  }

  const load = useCallback(async () => {
    if (!enabled) {
      setItems([]);
      setTotal(0);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await fetch({
        limit: pageSize,
        offset: pageToOffset(fetchPage, pageSize),
      });
      setItems(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      const message = messageOf(err);
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }, [enabled, fetch, fetchPage, onError, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    items,
    total,
    page: fetchPage,
    setPage,
    loading,
    error,
    reload: load,
    pageSize,
  };
}
