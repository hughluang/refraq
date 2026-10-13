"use client";

import { Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { getRun, listNodeTypes } from "@/features/channels/api";
import { formatFailedNode, formatRunSubject } from "@/features/channels/formatRunSubject";
import { formatRunError } from "@/features/channels/problemLabel";
import { RunErrorText } from "@/features/channels/RunErrorText";
import { ChannelCanvas } from "@/features/channels/ChannelCanvas";
import type { ChannelRunDetail as Detail, NodeTypeSpec } from "@/features/channels/types";
import { ApiError } from "@/lib/api";

export function ChannelRunDetail({
  channelId,
  jobId,
}: {
  channelId: string;
  jobId: string;
}) {
  const t = useTranslate();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [catalog, setCatalog] = useState<NodeTypeSpec[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    let cancelled = false;
    void listNodeTypes().then((page) => {
      if (!cancelled) setCatalog(page.items);
    });
    const load = () => {
      void getRun(channelId, jobId)
        .then((body) => {
          if (cancelled) return;
          setDetail(body);
          setError(null);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(
            err instanceof ApiError
              ? err
              : new ApiError(
                  0,
                  "REQUEST_FAILED",
                  err instanceof Error ? err.message : "Request failed",
                ),
          );
        });
    };
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [channelId, jobId]);
  if (error) return <PageError message={error.detail} requestId={error.requestId} />;
  if (!detail?.graph) return <PageBodySkeleton />;
  const subject = formatRunSubject(detail.run, t);
  const runError = formatRunError(t, detail.run.error_code, detail.run.error_message);
  const explanation =
    runError.detail && runError.detail !== runError.label ? runError.detail : null;
  const failedNode = formatFailedNode(detail.graph.nodes, detail.run.failed_node_id);
  return (
    <Stack gap="sm" style={{ height: "100%", minHeight: 0 }}>
      <Title order={3}>
        <Link href={`/console/channels/${channelId}`}>{t("channels.runDetail.back")}</Link>
      </Title>
      <Stack gap={4}>
        <Text>
          <JobStatusBadge status={detail.run.status} />
          {subject ? <> {subject}</> : null}
          {detail.run.ignore_checkpoints ? (
            <Text span size="xs" c="dimmed" ml={6}>
              {t("channels.runs.ignoreCheckpoints")}
            </Text>
          ) : null}
          {detail.run.stopped_node_id ? (
            <Text span size="xs" c="dimmed" ml={6}>
              {t("channels.runDetail.stoppedAt", { node: detail.run.stopped_node_id })}
            </Text>
          ) : null}
        </Text>
        {runError.label ? <Text size="sm">{runError.label}</Text> : null}
        {explanation ? (
          <Text size="sm" c="dimmed">
            {explanation}
          </Text>
        ) : null}
        {failedNode ? <Text size="sm">{failedNode}</Text> : null}
      </Stack>
      <div style={{ flex: 1, minHeight: 360 }}>
        <ChannelCanvas
          graph={detail.graph}
          catalog={catalog}
          editable={false}
          problems={[]}
          onChange={() => undefined}
        />
      </div>
      {detail.node_executions.map((item) => (
        <Text key={item.seq} size="sm">
          {item.node_id} {item.status}{" "}
          <RunErrorText code={item.error_code} message={item.error_message} />{" "}
          {JSON.stringify(item.output_preview)}
        </Text>
      ))}
    </Stack>
  );
}
