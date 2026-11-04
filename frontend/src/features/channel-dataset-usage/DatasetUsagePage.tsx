"use client";

import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageChrome } from "@/components/layout/PageChrome";
import { getDatasetCapacity, listChannelDatasets } from "@/features/channels/api";
import type { ChannelDatasetListItem, DatasetCapacity } from "@/features/channels/types";
import { CapacityBar } from "@/features/channel-dataset-usage/CapacityBar";
import { DatasetUsageTable } from "@/features/channel-dataset-usage/DatasetUsageTable";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { isSessionExpiredError } from "@/lib/api";

type Phase = "loading" | "ready" | "unloaded" | "expired";

export function DatasetUsagePage() {
  const t = useTranslate();
  const tRef = useRef(t);
  tRef.current = t;
  const query = useListQuery({ search: false });
  const list = useConsolePagedList<ChannelDatasetListItem>({
    pageSize: 50,
    fetch: listChannelDatasets,
    page: query.page,
    onPageChange: query.setPage,
  });
  const listReload = useRef(list.reload);
  listReload.current = list.reload;
  const [capacity, setCapacity] = useState<DatasetCapacity | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (attempt === 0) return;
    void listReload.current();
  }, [attempt]);

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
  const waitingForList = phase === "ready" && list.presentation.state === "loading";
  if (phase === "loading" || waitingForList) {
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
    <PageChrome title={title} description={description} fill>
      <CapacityBar capacity={capacity} />
      <FillColumn>
        <DatasetUsageTable list={list} />
      </FillColumn>
    </PageChrome>
  );
}
