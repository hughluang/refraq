"use client";

import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ApiError } from "@/lib/api";
import { getVersion } from "./api";
import type { ChannelVersion } from "./types";

export function usePublishedChannelVersion(channelId: string, number: number | null, refreshKey: unknown) {
  const t = useTranslate();
  const translate = useRef(t);
  translate.current = t;
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<{ version: ChannelVersion; refreshKey: unknown } | null>(null);

  useEffect(() => {
    setLoaded(null);
    if (number === null) return;
    let current = true;
    void getVersion(encodeURIComponent(channelId), number)
      .then(({ version }) => {
        if (current) setLoaded({ version, refreshKey });
      })
      .catch((error: unknown) => {
        if (!current || (error instanceof ApiError && [401, 403, 404].includes(error.status))) return;
        presentProblemNotification(translate.current, error, {
          onRetry: () => { if (current) setAttempt(value => value + 1); },
        });
      });
    return () => { current = false; };
  }, [channelId, number, refreshKey, attempt]);

  return loaded?.version.channel_id === channelId && loaded.version.number === number && loaded.refreshKey === refreshKey
    ? loaded.version : null;
}
