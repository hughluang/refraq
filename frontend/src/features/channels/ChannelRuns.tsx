"use client";

import { Anchor, Box, Group, Table, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { PencilIcon } from "@/components/icons";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listRuns } from "@/features/channels/api";
import { formatRunError } from "@/features/channels/problemLabel";
import { isTerminalRun } from "@/features/channels/runSession";
import { useLiveStatus, type LiveRefreshResult } from "@/hooks/useLiveStatus";
import { isSessionExpiredError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ChannelRuns({ channelId }: { channelId: string }) {
  const t = useTranslate();
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
    .map((run) => t(presentJobStatus(run.status).labelKey))
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
          const hasError = Boolean(run.error_code || run.error_message);
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
                  {run.ignore_checkpoints ? (
                    <Text span size="xs" c="dimmed">
                      {t("channels.runs.ignoreCheckpoints")}
                    </Text>
                  ) : null}
                  {run.target === "draft" ? <DraftMark label={t("channels.runs.subject.draft")} /> : null}
                </Group>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
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
