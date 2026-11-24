"use client";

import { useTranslate } from "@refinedev/core";
import { useRef } from "react";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";

export function useDiagnosticRead<T>(key: string, fetch: (signal: AbortSignal) => Promise<T>) {
  const t = useTranslate();
  const retry = useRef<() => void>(() => {});
  const live = useLiveStatus<{ status: "ready"; value: T } | { status: "forbidden" | "notFound" }>({
    key,
    fetch: async (signal, trigger) => {
      try { return { status: "ready", value: await fetch(signal) }; }
      catch (error) {
        if (error instanceof ApiError) {
          if (error.status === 401 || error.status === 403) return { status: "forbidden" };
          if (error.status === 404) return { status: "notFound" };
        }
        if (!signal.aborted && trigger !== "poll") presentProblemNotification(t, error, { onRetry: () => retry.current() });
        throw error;
      }
    },
    isTerminal: result => result.status !== "ready",
  });
  retry.current = live.refresh;
  return { ...live, value: live.data?.status === "ready" ? live.data.value : null,
    status: live.data?.status ?? (live.error ? "unloaded" as const : "loading" as const) };
}
