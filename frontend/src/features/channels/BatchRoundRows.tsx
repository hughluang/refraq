"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { listExecutions, previewTemplate } from "@/features/channels/api";
import { DatasetRowTable } from "@/features/channels/DatasetRows";
import {
  batchOrdWindow,
  batchReadRound,
  isDatasetReference,
  readBatchOutput,
  type DatasetReference,
} from "@/features/channels/datasetView";
import type { Graph, NodeExecution } from "@/features/channels/types";

export function BatchRoundRows({
  channelId,
  jobId,
  graph,
  execution,
}: {
  channelId: string;
  jobId: string;
  graph: Graph;
  execution: NodeExecution;
}) {
  const t = useTranslate();
  const round = batchReadRound(graph, execution);
  const [dataset, setDataset] = useState<DatasetReference | null>(null);
  const [ordWindow, setOrdWindow] = useState<{ afterOrd: number; endOrd: number } | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!round) return;
    let cancelled = false;
    setDataset(null);
    setOrdWindow(null);
    setMissing(false);
    void Promise.all([
      listExecutions(channelId, jobId, { node_id: round.parentId, limit: 200, offset: 0 }),
      previewTemplate(channelId, jobId, {
        graph,
        node_id: round.parentId,
        path: ["dataset"],
      }),
    ])
      .then(([page, preview]) => {
        if (cancelled) return;
        const container = page.items.find((item) => item.seq === round.containerSeq);
        const shape = readBatchOutput(container?.output_preview);
        const value = preview.state === "ok" ? preview.value : null;
        if (!shape || !isDatasetReference(value)) {
          setMissing(true);
          return;
        }
        setDataset(value);
        setOrdWindow(batchOrdWindow(round.index, shape.batchSize, shape.total));
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, jobId, graph, round?.parentId, round?.index, round?.containerSeq]);

  if (!round) return null;
  if (missing) {
    return (
      <Text size="xs" c="dimmed">
        {t("channels.run.dataset.roundMissing")}
      </Text>
    );
  }
  if (!dataset || !ordWindow) return null;
  return (
    <Stack gap={4}>
      <Text size="xs" fw={600}>
        {t("channels.run.dataset.round", { index: round.index })}
      </Text>
      <DatasetRowTable
        key={`${dataset.dataset_id}:${ordWindow.afterOrd}:${ordWindow.endOrd}`}
        channelId={channelId}
        jobId={jobId}
        datasetId={dataset.dataset_id}
        afterOrd={ordWindow.afterOrd}
        endOrd={ordWindow.endOrd}
        columns={dataset.columns}
      />
    </Stack>
  );
}
