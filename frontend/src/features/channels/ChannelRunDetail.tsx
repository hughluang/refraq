"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StaleNotice } from "@/components/display/StaleNotice";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus, presentNodeStatus } from "@/components/display/statusTone";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { getRun, listNodeTypes, rerunRun } from "@/features/channels/api";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { RecordReference } from "@/components/display/RecordReference";
import { formatFailedNode, formatRunSubject, nodeDisplayName } from "@/features/channels/formatRunSubject";
import { formatRunError } from "@/features/channels/problemLabel";
import { RunErrorText } from "@/features/channels/RunErrorText";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import { ChannelCanvas } from "@/features/channels/ChannelCanvas";
import { isTerminalRun } from "@/features/channels/runSession";
import type { NodeTypeSpec } from "@/features/channels/types";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

export function ChannelRunDetail({
  channelId,
  jobId,
}: {
  channelId: string;
  jobId: string;
}) {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const [catalog, setCatalog] = useState<NodeTypeSpec[]>([]);
  const [rerunning, setRerunning] = useState(false);
  const live = useLiveStatus({
    key: `${channelId}:${jobId}`,
    fetch: (signal) => getRun(channelId, jobId, { signal }),
    isTerminal: (body) => isTerminalRun(body.run.status),
  });
  const detail = live.data;
  const failed = live.stale && detail == null;
  const loadError = live.error instanceof ApiError ? live.error : null;
  useEffect(() => {
    let cancelled = false;
    void listNodeTypes().then((page) => {
      if (!cancelled) setCatalog(page.items);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const rerun =
    canWrite?.can && detail?.run.status === "failed" && detail.run.target === "published" ? (
      <Button
        size="sm"
        loading={rerunning}
        onClick={() => {
          setRerunning(true);
          void rerunRun(channelId, jobId)
            .then((body) => {
              window.location.assign(
                `/console/channels/${channelId}/runs/${body.run.job_id}`,
              );
            })
            .catch((error: unknown) => {
              open?.({
                type: "error",
                message: problemMessage(t, error, t("channels.runDetail.rerunFailed")),
              });
              setRerunning(false);
            });
        }}
      >
        {t("channels.runDetail.rerun")}
      </Button>
    ) : null;
  const back = (
    <HeaderActions
      navigation={
        <Group gap="xs">
          {rerun}
          <Button
            component={ConsoleLink}
            href={`/console/channels/${channelId}`}
            variant="default"
            size="sm"
          >
            {t("channels.runDetail.back")}
          </Button>
        </Group>
      }
    />
  );
  const graph = detail?.graph ?? null;
  if (!detail || !graph) {
    return (
      <PageChrome
        title={t("channels.title")}
        actions={back}
        status={failed ? "error" : "loading"}
        errorMessage={
          failed ? problemMessage(t, live.error, t("liveStatus.unavailable")) : undefined
        }
        requestId={loadError?.requestId}
        onRetry={() => void live.refresh()}
      />
    );
  }
  const subject = formatRunSubject(detail.run, t);
  const runError = formatRunError(t, detail.run.error_code, detail.run.error_message);
  const explanation =
    runError.detail && runError.detail !== runError.label ? runError.detail : null;
  const failedNode = formatFailedNode(graph.nodes, detail.run.failed_node_id);
  return (
    <PageChrome
      fill
      title={t("channels.title")}
      recordTitle={subject || detail.run.job_id}
      recent={{
        moduleId: "channels",
        title: subject || detail.run.job_id,
      }}
      titleExtra={<JobStatusBadge status={detail.run.status} />}
      actions={back}
    >
    <Stack gap="sm" style={{ height: "100%", minHeight: 0 }}>
      <LiveStatusAnnouncer text={t(presentJobStatus(detail.run.status).labelKey)} />
      {live.stale ? <StaleNotice onRetry={() => void live.refresh()} /> : null}
      <Stack gap={4}>
        {detail.run.ignore_checkpoints || detail.run.stopped_node_id ? (
          <Text>
            {detail.run.ignore_checkpoints ? (
              <Text span size="xs" c="dimmed">
                {t("channels.runs.ignoreCheckpoints")}
              </Text>
            ) : null}
            {detail.run.stopped_node_id ? (
              <Text span size="xs" c="dimmed" ml={detail.run.ignore_checkpoints ? 6 : 0}>
                {t("channels.runDetail.stoppedAt", {
                  node: nodeDisplayName(graph.nodes, detail.run.stopped_node_id),
                })}
              </Text>
            ) : null}
          </Text>
        ) : null}
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
          channelId={channelId}
          graph={graph}
          catalog={catalog}
          appearance="browse"
          mutable={false}
          sessionRun={detail}
          focusNodeId={detail.run.failed_node_id}
          problems={[]}
          onChange={() => undefined}
        />
      </div>
      {detail.node_executions.map((item) => {
        const label = nodeDisplayName(graph.nodes, item.node_id);
        const named = label != null && label !== item.node_id;
        return (
        <Stack key={item.seq} gap={4}>
          <Text size="sm">
            {named && label ? (
              <RecordReference name={label} recordKey={item.node_id} />
            ) : (
              item.node_id
            )}{" "}
            <StatusBadge
              size="xs"
              tone={presentNodeStatus(item.status).tone}
              labelKey={presentNodeStatus(item.status).labelKey}
            />{" "}
            <RunErrorText code={item.error_code} message={item.error_message} />
          </Text>
          <RunExecutionOutput channelId={channelId} jobId={jobId} item={item} />
        </Stack>
        );
      })}
    </Stack>
    </PageChrome>
  );
}
