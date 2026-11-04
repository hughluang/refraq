"use client";

import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { PageChrome } from "@/components/layout/PageChrome";
import { getDatasetCapacity } from "@/features/channels/api";
import type { DatasetCapacity } from "@/features/channels/types";
import { CapacityBar } from "@/features/channel-dataset-usage/CapacityBar";
import { isSessionExpiredError } from "@/lib/api";

type Phase = "loading" | "ready" | "unloaded" | "expired";

export function DatasetUsagePage() {
  const t = useTranslate();
  const tRef = useRef(t);
  tRef.current = t;
  const [capacity, setCapacity] = useState<DatasetCapacity | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setCapacity(null);
    getDatasetCapacity()
      .then((body) => {
        if (cancelled) return;
        setCapacity(body);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (isSessionExpiredError(error)) {
          setPhase("expired");
          return;
        }
        setPhase("unloaded");
        presentProblemNotification(tRef.current, error, {
          onRetry: () => setAttempt((value) => value + 1),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const title = t("channelDatasetUsage.title");
  const description = t("channelDatasetUsage.description");
  if (phase === "loading") {
    return <PageChrome title={title} description={description} status="loading" />;
  }
  if (phase === "unloaded") {
    return (
      <PageChrome
        title={title}
        description={description}
        status="unloaded"
        onRetry={() => setAttempt((value) => value + 1)}
      />
    );
  }
  if (phase === "expired" || capacity == null) {
    return <PageChrome title={title} description={description} />;
  }
  return (
    <PageChrome title={title} description={description}>
      <CapacityBar capacity={capacity} />
      {/* The dataset list renders here, under the bar. */}
    </PageChrome>
  );
}
