"use client";

import { Anchor, Box, Button, Group, Table, Text, Tooltip } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { PencilIcon } from "@/components/icons";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listRuns } from "@/features/channels/api";
import { formatFailedNode, nodeDisplayName } from "@/features/channels/formatRunSubject";
import { formatRunError } from "@/features/channels/problemLabel";
import { isTerminalRun } from "@/features/channels/runSession";
import type { ChannelRun } from "@/features/channels/types";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { cancelJob } from "@/features/jobs/api";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useLiveStatus, type LiveRefreshResult } from "@/hooks/useLiveStatus";
import { isSessionExpiredError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";

const PAGE_SIZE = 50;

/** Inbound runs name their kind and path. Other kinds keep the row they have today. */
export function inboundRunLabel(
  run: Pick<ChannelRun, "trigger_kind" | "trigger_ref">,
  t: (key: string) => string,
): string | null {
  if (run.trigger_kind !== "inbound") return null;
  const kind = t("channels.runs.trigger.inbound");
  const path = run.trigger_ref?.trim() ?? "";
  return path ? `${kind} · ${path}` : kind;
}

export function ChannelRuns({ channelId }: { channelId: string }) {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const { data: canJobs } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });
  const canStop = Boolean(canWrite?.can || canJobs?.can);
  const stopRun = useConsoleMutation();
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
  const [page, setPage] = useState(1);
  const live = useLiveStatus({
    key: `${channelId}:${page}`,
    onRefreshResult: reportRefreshFailure,
    fetch: (signal) =>
      listRuns(
        channelId,
        {
          limit: PAGE_SIZE,
          offset: pageToOffset(page, PAGE_SIZE),
        },
        { signal },
      ),
    isTerminal: (result) =>
      result.items.length > 0 && result.items.every((run) => isTerminalRun(run.status)),
  });
  const items = live.data?.items ?? [];
  const total = live.data?.total ?? 0;
  const sessionExpired = isSessionExpiredError(live.error);
  const unloaded = live.data == null && live.stale && !sessionExpired;
  retryRef.current = () => live.refresh();
  const freshness =
    live.data != null && live.stale && !sessionExpired
      ? { updatedAt: live.lastSuccessAt, onRefresh: () => void retryRef.current() }
      : null;
  useEffect(() => {
    if (live.data || !live.stale || sessionExpired) {
      if (live.data || !live.stale) unloadedNotice.current = false;
      return;
    }
    if (unloadedNotice.current) return;
    unloadedNotice.current = true;
    presentProblemNotification(tRef.current, live.error, {
      onRetry: () => {
        void retryRef.current();
      },
    });
  }, [live.data, live.error, live.stale, sessionExpired]);
  const statusText = items
    .map((run) => {
      const started = showInstant(run.started_at ?? run.created_at);
      return `${started} ${t(presentJobStatus(run.status).labelKey)}`;
    })
    .join(", ");
  const list = {
    presentation: listPresentationOf({
      loading: live.loading || live.refreshing || (sessionExpired && live.data == null),
      error: unloaded ? "unloaded" : null,
      total,
      itemCount: items.length,
      filtered: false,
    }),
    error: null,
    errorRequestId: null,
    reload: () => live.refresh(),
    page,
    setPage,
    pageSize: PAGE_SIZE,
    total,
  };

  return (
    <div className="channel-drawer-list">
      <LiveStatusAnnouncer text={statusText} />
      <ListTable
        list={list}
        columnCount={1}
        minWidth={420}
        emptyMessage={t("channels.runs.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.runs.started")}</Table.Th>
          </Table.Tr>
        }
      >
        {items.map((run) => {
          const presentation = presentJobStatus(run.status);
          const error = formatRunError(t, run.error_code, run.error_message);
          const errorDetail =
            error.detail && error.detail !== error.label ? error.detail : null;
          const hasError = Boolean(run.error_code || run.error_message);
          const failedNode =
            run.status === "failed" ? formatFailedNode([], run.failed_node_id) : null;
          const stoppedNode =
            run.status === "cancelled" ? nodeDisplayName([], run.stopped_node_id) : null;
          const showError = run.status === "failed" || run.status === "cancelled";
          const inbound = inboundRunLabel(run, t);
          const href = `/console/channels/${channelId}/runs/${run.job_id}`;
          return (
            <Table.Tr key={run.job_id}>
              <Table.Td>
                <Group gap="xs" wrap="nowrap" align="center">
                  <StatusBadge
                    size="xs"
                    tone={presentation.tone}
                    labelKey={presentation.labelKey}
                    explanation={hasError && error.label ? error.label : null}
                    freshness={freshness}
                  />
                  <Anchor component={ConsoleLink} href={href} size="sm">
                    <Instant value={run.started_at ?? run.created_at} />
                  </Anchor>
                  <Text span size="sm">
                    {t("jobs.fields.duration")}: {formatJobDuration(run)}
                  </Text>
                  {failedNode ? (
                    <Text span size="sm">
                      {failedNode}
                    </Text>
                  ) : null}
                  {stoppedNode ? (
                    <Text span size="sm">
                      {t("channels.runDetail.stoppedAt", { node: stoppedNode })}
                    </Text>
                  ) : null}
                  {showError && error.label ? (
                    <Text span size="sm">
                      {error.label}
                    </Text>
                  ) : null}
                  {showError && errorDetail ? (
                    <Text span size="sm" c="dimmed">
                      {errorDetail}
                    </Text>
                  ) : null}
                  {inbound ? (
                    <Text span size="xs" c="dimmed">
                      {inbound}
                    </Text>
                  ) : null}
                  {run.ignore_checkpoints ? (
                    <Text span size="xs" c="dimmed">
                      {t("channels.runs.ignoreCheckpoints")}
                    </Text>
                  ) : null}
                  {run.target === "draft" ? <DraftMark label={t("channels.runs.subject.draft")} /> : null}
                  {!isTerminalRun(run.status) && canStop ? (
                    <Button
                      type="button"
                      size="xs"
                      color="red"
                      variant="light"
                      loading={stopRun.isSubmitting(run.job_id)}
                      onClick={() => {
                        const name = showInstant(run.started_at ?? run.created_at);
                        stopRun.run({
                          key: run.job_id,
                          safety: "confirm",
                          recordName: name,
                          title: t("channels.run.stop.confirmTitle", { name }),
                          consequence: t("channels.run.stop.consequence"),
                          confirmLabel: t("channels.run.stop"),
                          confirmColor: "red",
                          outcome: t("channels.run.stop.outcome"),
                          execute: () => cancelJob(run.job_id),
                          onSuccess: () => live.refresh(),
                        });
                      }}
                    >
                      {t("channels.run.stop")}
                    </Button>
                  ) : null}
                </Group>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
      {stopRun.dialog}
    </div>
  );
}

function DraftMark({ label }: { label: string }) {
  return (
    <Tooltip label={label}>
      <Box
        component="span"
        role="img"
        aria-label={label}
        style={{ display: "inline-flex", flex: "none" }}
      >
        <PencilIcon size={14} />
      </Box>
    </Tooltip>
  );
}
