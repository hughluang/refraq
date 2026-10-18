"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const LIVE_STATUS_INTERVAL_MS = 2000;

export type UseLiveStatusOptions<T> = {
  fetch: (signal: AbortSignal) => Promise<T>;
  isTerminal: (data: T) => boolean;
  enabled?: boolean;
  key?: string | number | null;
};

export type LiveStatusState<T> = {
  data: T | null;
  error: unknown;
  stale: boolean;
  /** True only before the first result, while a fetch is in flight. */
  loading: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
};

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useLiveStatus<T>(options: UseLiveStatusOptions<T>): LiveStatusState<T> {
  const enabled = options.enabled ?? true;
  const key = options.key ?? null;

  const fetchRef = useRef(options.fetch);
  const terminalRef = useRef(options.isTerminal);
  fetchRef.current = options.fetch;
  terminalRef.current = options.isTerminal;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [stale, setStale] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const dataRef = useRef<T | null>(null);
  const pausedRef = useRef(typeof document !== "undefined" && document.hidden);
  const requestSeq = useRef(0);
  const runRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    if (!enabled) {
      runRef.current = async () => {};
      return;
    }

    let alive = true;
    const controllers = new Set<AbortController>();
    dataRef.current = null;
    setData(null);
    setError(null);
    setStale(false);
    setRefreshing(false);

    const run = (): Promise<void> => {
      if (!alive) return Promise.resolve();
      const seq = ++requestSeq.current;
      const controller = new AbortController();
      controllers.add(controller);
      setRefreshing(true);
      return fetchRef
        .current(controller.signal)
        .then((next) => {
          if (!alive || seq !== requestSeq.current) return;
          dataRef.current = next;
          setData(next);
          setError(null);
          setStale(false);
        })
        .catch((err: unknown) => {
          if (!alive || seq !== requestSeq.current) return;
          if (controller.signal.aborted || isAbortError(err)) return;
          setError(err);
          setStale(true);
        })
        .finally(() => {
          controllers.delete(controller);
          if (alive && seq === requestSeq.current) setRefreshing(false);
        });
    };

    runRef.current = run;

    const terminal = () =>
      dataRef.current != null && terminalRef.current(dataRef.current);

    if (!pausedRef.current) void run();

    const timer = window.setInterval(() => {
      if (!alive || pausedRef.current || terminal()) return;
      void run();
    }, LIVE_STATUS_INTERVAL_MS);

    const onVisibility = () => {
      const hidden = document.hidden;
      pausedRef.current = hidden;
      if (!hidden && alive && !terminal()) void run();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      alive = false;
      requestSeq.current += 1;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      for (const controller of controllers) controller.abort();
      controllers.clear();
      runRef.current = async () => {};
    };
  }, [enabled, key]);

  const refresh = useCallback(() => runRef.current(), []);

  return {
    data,
    error,
    stale,
    loading: data == null && refreshing && !stale,
    refreshing,
    refresh,
  };
}
