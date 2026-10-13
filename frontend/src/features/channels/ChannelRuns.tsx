"use client";

import { Box, Group, Table, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListPager } from "@/components/display/ListPager";
import { EmptyState } from "@/components/feedback/EmptyState";
import { listRuns } from "@/features/channels/api";
import { formatRunError } from "@/features/channels/problemLabel";
import type { ChannelRun } from "@/features/channels/types";
import { JOB_STATUS_COLOR } from "@/features/jobs/JobStatusBadge";
import { pageToOffset } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ChannelRuns({ channelId }: { channelId: string }) {
  const t = useTranslate();
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ChannelRun[]>([]);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      void listRuns(channelId, {
        limit: PAGE_SIZE,
        offset: pageToOffset(page, PAGE_SIZE),
      }).then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      });
    };
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [channelId, page]);
  if (total === 0) return <EmptyState message={t("channels.runs.empty")} />;
  return (
    <div className="channel-drawer-list">
      <div className="channel-drawer-list__scroll">
        <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t("channels.runs.started")}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {items.map((run) => {
          const color = JOB_STATUS_COLOR[run.status] ?? "gray";
          const error = formatRunError(t, run.error_code, run.error_message);
          const hasError = Boolean(run.error_code || run.error_message);
          const statusLabel = hasError && error.label ? error.label : run.status;
          const href = `/console/channels/${channelId}/runs/${run.job_id}`;
          const open = () => router.push(href);
          return (
            <Table.Tr
              key={run.job_id}
              tabIndex={0}
              style={{ cursor: "pointer" }}
              onClick={open}
              onKeyDown={(event) => {
                if (event.key === "Enter") open();
              }}
            >
              <Table.Td>
                <Group gap="xs" wrap="nowrap" align="center">
                  <Tooltip label={statusLabel}>
                    <Box
                      role="img"
                      aria-label={statusLabel}
                      w={8}
                      h={8}
                      bg={`${color}.6`}
                      style={{ borderRadius: 999, flex: "none" }}
                    />
                  </Tooltip>
                  <Instant value={run.started_at ?? run.created_at} />
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
      </Table.Tbody>
        </Table>
      </div>
      <ListPager page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />
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
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
        </svg>
      </Box>
    </Tooltip>
  );
}
