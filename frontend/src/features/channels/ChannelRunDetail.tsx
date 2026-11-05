"use client";

import { ActionIcon, Button, Group, Stack, Text, Tooltip } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useSearchParams } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { CopyIcon } from "@/components/icons";
import { historyContext, historyReturn } from "@/features/channels/channelHistory";
import { formatJobDuration } from "@/lib/datetime";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { presentJobStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { cancelJob } from "@/features/jobs/api";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { getRun, listExecutions, listNodeTypes, rerunRun } from "@/features/channels/api";
import { latestExecutionQuery } from "@/features/channels/datasetView";
import { RunExecutionBrowser } from "@/features/channels/RunExecutionBrowser";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { inboundRunLabel } from "@/features/channels/ChannelRuns";
import {
  formatFailedNode,
  formatRunSubject,
  nodeDisplayName,
} from "@/features/channels/formatRunSubject";
import { formatRunError } from "@/features/channels/problemLabel";
import { ChannelCanvas, type RunNodeOpen } from "@/features/channels/ChannelCanvas";
import { runDetailArrangement, type RunDetailArrangement } from "@/features/channels/runDetailArrangement";
import "./ChannelRunDetail.css";
import { containerRoundPins, isTerminalRun, recordedKey } from "@/features/channels/runSession";
import type { NodeExecution, NodeTypeSpec } from "@/features/channels/types";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useLiveStatus, type LiveRefreshResult } from "@/hooks/useLiveStatus";
import { isSessionExpiredError } from "@/lib/api";
import { copyText } from "@/lib/copy-text";
import { problemMessage } from "@/lib/problem";

export function ChannelRunDetail({
  channelId,
  jobId,
}: {
  channelId: string;
  jobId: string;
}) {
  const { push } = useConsoleNavigation();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const returnHref = historyReturn(channelId, search);
  const t = useTranslate();
  const { open } = useNotification();
  const showInstant = useShowInstant();
  const stopRunAction = useConsoleMutation();
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const { data: canJobs } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });
  const canStop = Boolean(canWrite?.can || canJobs?.can);
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
  const [executionReload, setExecutionReload] = useState(0);
  const gesture = useRef(0);
  const [selectionRequest, setSelectionRequest] = useState<{ seq: number; token: number } | null>(
    null,
  );
  const [runNodeFocus, setRunNodeFocus] = useState<{
    token: number;
    nodeId: string;
    pins: Record<string, number>;
  } | null>(null);
  const recorded = useRef<string | null>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [arrangement, setArrangement] = useState<RunDetailArrangement>("band");
  const [indexOpen, setIndexOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorHost, setInspectorHost] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    gesture.current += 1;
    setSelectionRequest(null);
    setRunNodeFocus(null);
    setRerunning(false);
    return () => { gesture.current += 1; };
  }, [channelId, jobId]);
  const summaryKey = detail ? recordedKey(detail) : null;
  useEffect(() => {
    if (!summaryKey) {
      recorded.current = null;
      return;
    }
    const prior = recorded.current;
    recorded.current = summaryKey;
    // The first key after a gap is the page the browser already loads.
    if (prior && prior !== summaryKey) {
      setExecutionReload((token) => token + 1);
    }
  }, [summaryKey]);
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
  const hasGraph = detail?.graph != null;
  useLayoutEffect(() => {
    const el = workspaceRef.current;
    if (!el) return;
    const apply = () => {
      const font = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
      setArrangement(runDetailArrangement(el.clientWidth, Number.isFinite(font) ? font : 16));
    };
    apply();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(apply);
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasGraph]);
  const rerun =
    canWrite?.can && detail?.run.status === "failed" && detail.run.target === "published" && detail.run.version != null ? (
      <Button
        size="sm"
        loading={rerunning}
        onClick={() => {
          setRerunning(true);
          void rerunRun(channelId, jobId)
            .then((body) => {
              push(
                `/console/channels/${channelId}/runs/${body.run.job_id}?${historyContext(window.location.search)}`,
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
  const stopHeader =
    canStop && detail && !isTerminalRun(detail.run.status) ? (
      <Button
        type="button"
        size="sm"
        color="red"
        variant="light"
        loading={stopRunAction.submitting}
        onClick={() => {
          const name = showInstant(detail.run.started_at ?? detail.run.created_at);
          stopRunAction.run({
            safety: "confirm",
            recordName: name,
            title: t("channels.run.stop.confirmTitle", { name }),
            consequence: t("channels.run.stop.consequence"),
            confirmLabel: t("channels.run.stop"),
            confirmColor: "red",
            outcome: t("channels.run.stop.outcome"),
            execute: () => cancelJob(jobId),
            onSuccess: () => live.refresh(),
          });
        }}
      >
        {t("channels.run.stop")}
      </Button>
    ) : null;
  const back = (
    <HeaderActions
      navigation={
        <Group gap="xs">
          {rerun}
          <Button
            component={ConsoleLink}
            href={returnHref}
            variant="default"
            size="sm"
          >
            {t("channels.runDetail.back")}
          </Button>
        </Group>
      }
      lifecycle={stopHeader}
    />
  );
  const graph = detail?.graph ?? null;
  if (!detail) {
    const unloaded = detail == null && live.stale && !sessionExpired;
    return (
      <>
        <PageChrome
          title={t("channels.title")}
          actions={back}
          status={unloaded ? "unloaded" : "loading"}
          onRetry={unloaded ? () => void retryRef.current() : undefined}
        />
        {stopRunAction.dialog}
      </>
    );
  }
  const subject = formatRunSubject(detail.run, t);
  const inbound = inboundRunLabel(detail.run, t);
  const triggerLabel =
    detail.run.trigger_kind === "retry" || detail.run.trigger_kind === "error"
      ? t(`channels.runs.trigger.${detail.run.trigger_kind}`)
      : inbound ?? formatJobTrigger(detail.run, t);
  const copyLabel = t("channels.runs.copyId", { id: detail.run.job_id });
  const runError = formatRunError(t, detail.run.error_code, detail.run.error_message);
  const explanation =
    runError.detail && runError.detail !== runError.label ? runError.detail : null;
  const failedNode = formatFailedNode(graph?.nodes ?? [], detail.run.failed_node_id);
  const chooseExecution = (seq: number) => {
    setSelectionRequest((current) => ({ seq, token: (current?.token ?? 0) + 1 }));
  };
  const onRunNodeOpen = (open: RunNodeOpen) => {
    const generation = ++gesture.current;
    if (open.status === "none") return;
    if (open.status === "ready") {
      chooseExecution(open.execution.seq);
      return;
    }
    const summary = detail.node_summaries.find((item) => item.node_id === open.nodeId);
    const query = summary ? latestExecutionQuery(summary) : null;
    if (!query) return;
    void listExecutions(channelId, jobId, query).then((page) => {
      if (gesture.current !== generation) return;
      const execution = page.items.find((item) => item.node_id === open.nodeId);
      if (!execution) return;
      chooseExecution(execution.seq);
    });
  };
  const onExecutionSelect = (execution: NodeExecution) => {
    const generation = ++gesture.current;
    void containerRoundPins(execution, async (seq) => {
      const page = await listExecutions(channelId, jobId, { limit: 1, offset: seq - 1 });
      const item = page.items[0];
      if (!item || item.seq !== seq) return null;
      return item;
    }).then((pins) => {
      if (gesture.current !== generation) return;
      setRunNodeFocus((current) => ({
        token: (current?.token ?? 0) + 1,
        nodeId: execution.node_id,
        pins,
      }));
    });
  };
  return (
    <PageChrome
      title={t("channels.title")}
      recordTitle={subject || detail.run.job_id}
      recent={{
        moduleId: "channels",
        title: subject || detail.run.job_id,
      }}
      titleExtra={<JobStatusBadge status={detail.run.status} freshness={freshness} />}
      actions={back}
      fill
    >
    <Stack gap="sm" flex={1} mih={0} style={{ minHeight: 0, overflow: "hidden" }}>
      <LiveStatusAnnouncer text={t(presentJobStatus(detail.run.status).labelKey)} />
      <Group gap="xs" wrap="wrap" align="center" style={{ minWidth: 0 }}>
        <Group gap={4} wrap="nowrap" align="baseline">
          {detail.run.started_at ? null : <Text size="xs" c="dimmed">{t("jobs.fields.created")}</Text>}
          <Text size="xs" c="dimmed"><Instant value={detail.run.started_at ?? detail.run.created_at} /></Text>
        </Group>
        <Text size="xs" c="dimmed">{t("jobs.fields.duration")}: {formatJobDuration(detail.run)}</Text>
        <Text size="xs" c="dimmed">{triggerLabel}</Text>
        {detail.run.target === "draft" && detail.run.draft_revision != null ? (
          <Text size="xs" c="dimmed">{t("channels.runs.revision", { number: detail.run.draft_revision })}</Text>
        ) : null}
        <Group gap={4} wrap="nowrap" align="center" className="channel-history-id">
          <Tooltip label={detail.run.job_id}>
            <Text className="channel-history-id__value" component="span" size="xs" c="dimmed" ff="monospace">{detail.run.job_id}</Text>
          </Tooltip>
          <Tooltip label={copyLabel}>
            <ActionIcon className="channel-history-id__copy" type="button" variant="subtle" size="sm" aria-label={copyLabel} onClick={() => {
              void copyText(detail.run.job_id).then(() => open?.({ type: "success", message: t("common.copy.success") }), () => open?.({ type: "error", message: t("common.copy.failed") }));
            }}>
              <CopyIcon size={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
      {detail.run.stop_at_node_id ? <Text size="sm">{t("channels.runs.partial", { node: nodeDisplayName(graph?.nodes ?? [], detail.run.stop_at_node_id) })}</Text> : null}
      {rerun ? <Text size="xs" c="dimmed">{t("channels.runDetail.rerunConsequence")}</Text> : null}
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
                node: nodeDisplayName(graph?.nodes ?? [], detail.run.stopped_node_id),
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
      {graph ? (
      <div
        ref={workspaceRef}
        className={`channel-run-workspace channel-run-workspace--${arrangement}`}
        data-arrangement={arrangement}
        data-index={indexOpen ? "true" : "false"}
        data-inspector={inspectorOpen ? "true" : "false"}
        data-testid="run-detail-workspace"
      >
        <div className="channel-run-workspace__index" data-open={indexOpen ? "true" : "false"}>
          <RunExecutionBrowser
            channelId={channelId}
            jobId={jobId}
            graph={graph}
            reloadToken={executionReload}
            selectionRequest={selectionRequest}
            onExecutionSelect={onExecutionSelect}
            collapsed={!indexOpen}
            onToggleCollapsed={() => setIndexOpen((open) => !open)}
          />
        </div>
        <div className="channel-run-workspace__graph">
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
            onRunNodeOpen={onRunNodeOpen}
            runNodeFocus={runNodeFocus}
            inspectorHost={inspectorHost}
            onInspectorOpenChange={setInspectorOpen}
          />
        </div>
        <div
          className="channel-run-workspace__inspector"
          data-open={inspectorOpen ? "true" : "false"}
          data-testid="run-detail-inspector"
        >
          <div ref={setInspectorHost} className="channel-run-inspector-host" />
        </div>
      </div>
      ) : <Text size="sm" c="dimmed">{t(isTerminalRun(detail.run.status) ? "channels.runDetail.graphUnavailable" : "channels.runDetail.graphPending")}</Text>}
      {stopRunAction.dialog}
    </Stack>
    </PageChrome>
  );
}
