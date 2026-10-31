"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const LIVE_STATUS_INTERVAL_MS = 2000;

export type UseLiveStatusOptions<T> = {
  fetch: (signal: AbortSignal) => Promise<T>;
  isTerminal: (data: T) => boolean;
  enabled?: boolean;
  key?: string | number | null;
  /** Fires for `refresh` only. Interval polls do not call it. */
  onRefreshResult?: (result: LiveRefreshResult) => void;
};

export type LiveRefreshResult =
  | { ok: true }
  | { ok: false; error: unknown };

export type LiveStatusState<T> = {
  data: T | null;
  error: unknown;
  stale: boolean;
  /** True only before the first result, while a fetch is in flight. */
  loading: boolean;
  refreshing: boolean;
  /** Platform Instant text of the last successful fetch. Null before one succeeds. */
  lastSuccessAt: string | null;
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
  const refreshResultRef = useRef(options.onRefreshResult);
  fetchRef.current = options.fetch;
  terminalRef.current = options.isTerminal;
  refreshResultRef.current = options.onRefreshResult;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [stale, setStale] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<string | null>(null);

  const dataRef = useRef<T | null>(null);
  const pausedRef = useRef(typeof document !== "undefined" && document.hidden);
  const requestSeq = useRef(0);
  const runRef = useRef<() => Promise<LiveRefreshResult>>(async () => ({ ok: true }));

  useEffect(() => {
    if (!enabled) {
      runRef.current = async () => ({ ok: true });
      return;
    }

    let alive = true;
    const controllers = new Set<AbortController>();
    dataRef.current = null;
    setData(null);
    setError(null);
    setStale(false);
    setRefreshing(false);
    setLastSuccessAt(null);

    const run = (): Promise<LiveRefreshResult> => {
      if (!alive) return Promise.resolve({ ok: true });
      const seq = ++requestSeq.current;
      const controller = new AbortController();
      controllers.add(controller);
      setRefreshing(true);
      return fetchRef
        .current(controller.signal)
        .then((next): LiveRefreshResult => {
          if (!alive || seq !== requestSeq.current) return { ok: true };
          dataRef.current = next;
          setData(next);
          setError(null);
          setStale(false);
          setLastSuccessAt(new Date().toISOString());
          return { ok: true };
        })
        .catch((err: unknown): LiveRefreshResult => {
          if (!alive || seq !== requestSeq.current) return { ok: true };
          if (controller.signal.aborted || isAbortError(err)) return { ok: true };
          setError(err);
          setStale(true);
          return { ok: false, error: err };
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
      runRef.current = async () => ({ ok: true });
    };
  }, [enabled, key]);

  const refresh = useCallback((): Promise<void> => {
    return runRef.current().then((result) => {
      refreshResultRef.current?.(result);
    });
  }, []);

  return {
    data,
    error,
    stale,
    loading: data == null && refreshing && !stale,
    refreshing,
    lastSuccessAt,
    refresh,
  };
}
