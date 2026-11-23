"use client";

import { useTranslate } from "@refinedev/core";
import { useRef } from "react";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { getMirror } from "./api";
import { currentOpen } from "./MirrorEvidence";
import { getMirrorStopEvidence } from "./stopEvidence";

type MirrorRead =
  | { status: "ready"; result: Awaited<ReturnType<typeof getMirror>> }
  | { status: "forbidden" | "notFound" };

export function useMirrorStatus(id: string) {
  const t = useTranslate();
  const retry = useRef<() => void>(() => {});
  const live = useLiveStatus<MirrorRead>({
    key: id,
    fetch: async (signal, trigger) => {
      try {
        return { status: "ready", result: await getMirror(id, signal) };
      } catch (error) {
        if (!signal.aborted && trigger !== "poll") {
          presentProblemNotification(t, error, { onRetry: () => retry.current() });
        }
        if (error instanceof ApiError) {
          if (error.status === 403 || error.status === 401) return { status: "forbidden" };
          if (error.status === 404) return { status: "notFound" };
        }
        throw error;
      }
    },
    isTerminal: data => {
      if (data.status !== "ready") return true;
      const { mirror } = data.result;
      return !mirror.deletion_operation_id && !mirror.blocker && mirror.latest_request?.outcome !== "awaiting_recheck"
        && currentOpen(mirror)?.state !== "pending" && getMirrorStopEvidence(mirror)?.state !== "pending";
    },
  });
  retry.current = live.refresh;
  const result = live.data?.status === "ready" ? live.data.result : null;
  return {
    mirror: result?.mirror ?? null,
    canEnable: result?.can_enable ?? false,
    status: live.data?.status ?? (live.error ? "unloaded" as const : "loading" as const),
    stale: Boolean(result && live.stale),
    lastSuccessAt: live.lastSuccessAt,
    refresh: live.refresh,
  };
}
