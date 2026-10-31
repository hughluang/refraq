"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { presentJobStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { getRun, listNodeTypes, rerunRun } from "@/features/channels/api";
import { RunExecutionBrowser } from "@/features/channels/RunExecutionBrowser";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { formatFailedNode, formatRunSubject, nodeDisplayName } from "@/features/channels/formatRunSubject";
import { formatRunError } from "@/features/channels/problemLabel";
import { ChannelCanvas } from "@/features/channels/ChannelCanvas";
import { isTerminalRun } from "@/features/channels/runSession";
import type { NodeTypeSpec } from "@/features/channels/types";
import { useLiveStatus, type LiveRefreshResult } from "@/hooks/useLiveStatus";
import { isSessionExpiredError } from "@/lib/api";
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
  const tRef = useRef(t);
  tRef.current = t;
  const unloadedNotice = useRef(false);
  const retryRef = useRef<() => Promise<void>>(async () => {});
  const reportRefreshFailure = (result: LiveRefreshResult) => {
    if (result.ok || isSessionExpiredError(result.error)) return;
    presentProblemNotification(tRef.current, result.error, {
      onRetry: () => {
        void retryRef.current();
      },
    });
  };
  const live = useLiveStatus({
    key: `${channelId}:${jobId}`,
    onRefreshResult: reportRefreshFailure,
    fetch: (signal) => getRun(channelId, jobId, { signal }),
    isTerminal: (body) => isTerminalRun(body.run.status),
  });
  const detail = live.data;
  const sessionExpired = isSessionExpiredError(live.error);
  retryRef.current = () => live.refresh();
  const freshness =
    detail && live.stale && !sessionExpired
      ? { updatedAt: live.lastSuccessAt, onRefresh: () => void retryRef.current() }
      : null;
  useEffect(() => {
    if (detail || !live.stale || sessionExpired) {
      if (detail || !live.stale) unloadedNotice.current = false;
      return;
    }
    if (unloadedNotice.current) return;
    unloadedNotice.current = true;
    presentProblemNotification(tRef.current, live.error, {
      onRetry: () => {
        void retryRef.current();
      },
    });
  }, [detail, live.error, live.stale, sessionExpired]);
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
    const unloaded = detail == null && live.stale && !sessionExpired;
    return (
      <PageChrome
        title={t("channels.title")}
        actions={back}
        status={unloaded ? "unloaded" : "loading"}
        onRetry={unloaded ? () => void retryRef.current() : undefined}
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
      titleExtra={<JobStatusBadge status={detail.run.status} freshness={freshness} />}
      actions={back}
    >
    <Stack gap="sm" style={{ height: "100%", minHeight: 0 }}>
      <LiveStatusAnnouncer text={t(presentJobStatus(detail.run.status).labelKey)} />
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
      <RunExecutionBrowser channelId={channelId} jobId={jobId} graph={graph} catalog={catalog} />
    </Stack>
    </PageChrome>
  );
}
