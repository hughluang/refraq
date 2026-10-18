"use client";

import { Anchor, Box, Group, Table, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StaleNotice } from "@/components/display/StaleNotice";
import { presentJobStatus, toneVariable } from "@/components/display/statusTone";
import { PencilIcon } from "@/components/icons";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listRuns } from "@/features/channels/api";
import { formatRunError } from "@/features/channels/problemLabel";
import { isTerminalRun } from "@/features/channels/runSession";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";

const PAGE_SIZE = 50;

export function ChannelRuns({ channelId }: { channelId: string }) {
  const t = useTranslate();
  const [page, setPage] = useState(1);
  const live = useLiveStatus({
    key: `${channelId}:${page}`,
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
  const failed = live.stale && live.data == null;
  const errorText = problemMessage(t, live.error, t("liveStatus.unavailable"));
  const statusText = items
    .map((run) => t(presentJobStatus(run.status).labelKey))
    .join(", ");
  const list = {
    presentation: listPresentationOf({
      loading: live.loading || live.refreshing,
      error: failed ? errorText : null,
      total,
      itemCount: items.length,
      filtered: false,
    }),
    error: failed ? errorText : null,
    errorRequestId: live.error instanceof ApiError ? live.error.requestId : null,
    reload: () => live.refresh(),
    page,
    setPage,
    pageSize: PAGE_SIZE,
    total,
  };

  return (
    <div className="channel-drawer-list">
      <LiveStatusAnnouncer text={statusText} />
      {live.stale && live.data != null ? (
        <StaleNotice hasData onRetry={() => void live.refresh()} />
      ) : null}
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
          const statusLabel = t(presentation.labelKey);
          const tip = hasError && error.label ? error.label : statusLabel;
          const href = `/console/channels/${channelId}/runs/${run.job_id}`;
          return (
            <Table.Tr key={run.job_id}>
              <Table.Td>
                <Group gap="xs" wrap="nowrap" align="center">
                  <Tooltip label={tip}>
                    <Box
                      role="img"
                      aria-label={statusLabel}
                      w={8}
                      h={8}
                      style={{
                        borderRadius: 999,
                        flex: "none",
                        background: toneVariable(presentation.tone),
                      }}
                    />
                  </Tooltip>
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
