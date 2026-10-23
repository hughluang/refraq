"use client";

import { Button, Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { getExecutionOutput } from "@/features/channels/api";
import { DatasetCard } from "@/features/channels/DatasetRows";
import { datasetReferencesIn } from "@/features/channels/datasetView";
import { RunErrorText } from "@/features/channels/RunErrorText";
import type { ExecutionOutputPage, NodeExecution } from "@/features/channels/types";
import { problemMessage } from "@/lib/problem";

const OUTPUT_PAGE_SIZE = 200;

export function RunExecutionOutput({
  channelId,
  jobId,
  item,
}: {
  channelId: string;
  jobId: string;
  item: NodeExecution;
}) {
  const t = useTranslate();
  const [fullOutput, setFullOutput] = useState<unknown>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previewOnly = item.preview_only === true;
  const totals = item.preview_totals ?? {};

  if (item.status === "failed" || item.error_message) {
    return (
      <Text size="xs" c="red">
        <RunErrorText code={item.error_code} message={item.error_message} />
      </Text>
    );
  }

  const output = fullOutput === undefined ? item.output_preview : fullOutput;
  const references = datasetReferencesIn(output);
  const showFull =
    item.output_truncated && fullOutput === undefined && !previewOnly && references.length === 0;
  return (
    <Stack gap={4}>
      {previewOnly ? (
        <Stack gap={2}>
          <Text size="xs">{t("channels.run.previewOnly")}</Text>
          {Object.entries(totals).map(([path, count]) => (
            <Text key={path} size="xs" c="dimmed">
              {t("channels.run.previewTotal", { path, count })}
            </Text>
          ))}
        </Stack>
      ) : null}
      {references.map((dataset) => (
        <DatasetCard
          key={dataset.dataset_id}
          channelId={channelId}
          jobId={jobId}
          dataset={dataset}
        />
      ))}
      {references.length === 0 ? <Code block>{JSON.stringify(output, null, 2)}</Code> : null}
      {showFull ? (
        <Button
          size="compact-xs"
          variant="default"
          loading={loading}
          onClick={() => {
            setLoading(true);
            setError(null);
            void loadFullOutput(channelId, jobId, item.seq)
              .then(setFullOutput)
              .catch((reason: unknown) => {
                setError(problemMessage(t, reason, t("channels.run.outputFailed")));
              })
              .finally(() => setLoading(false));
          }}
        >
          {t("channels.run.showFullOutput")}
        </Button>
      ) : null}
      {error ? (
        <Text size="xs" c="red" role="alert">
          {error}
        </Text>
      ) : null}
    </Stack>
  );
}

async function loadFullOutput(channelId: string, jobId: string, seq: number): Promise<unknown> {
  const first = await getExecutionOutput(channelId, jobId, seq, {
    limit: OUTPUT_PAGE_SIZE,
    offset: 0,
  });
  if ("value" in first) return first.value;
  const items = [...first.items];
  let page: ExecutionOutputPage = first;
  while ("items" in page && items.length < page.total) {
    page = await getExecutionOutput(channelId, jobId, seq, {
      limit: OUTPUT_PAGE_SIZE,
      offset: items.length,
    });
    if (!("items" in page) || page.items.length === 0) break;
    items.push(...page.items);
  }
  return items;
}
