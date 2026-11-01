"use client";

import { Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { listInboundRejections, type InboundRejection } from "@/features/channels/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

const REASON_KEYS = new Set([
  "inactive",
  "method_not_allowed",
  "body_too_large",
  "unauthenticated",
  "input_invalid",
  "duplicate_in_flight",
  "busy",
]);

export function ChannelRejections({ channelId }: { channelId: string }) {
  const t = useTranslate();
  const [hitCount, setHitCount] = useState<number | null>(null);
  const fetchPage = useCallback(
    async (query: PageQuery) => {
      const page = await listInboundRejections(channelId, query);
      setHitCount(page.hit_count);
      return page;
    },
    [channelId],
  );
  const list = useConsolePagedList<InboundRejection>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [channelId],
  });

  return (
    <Stack gap="xs" className="channel-drawer-list">
      <Text size="sm">{t("channels.rejections.refusedOnly")}</Text>
      {hitCount != null ? (
        <Text size="sm">{t("channels.rejections.hitCount", { count: hitCount })}</Text>
      ) : null}
      <ListTable
        list={list}
        columnCount={2}
        minWidth={420}
        emptyMessage={t("channels.rejections.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.rejections.received")}</Table.Th>
            <Table.Th>{t("channels.rejections.reason")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <Instant value={row.received_at} />
            </Table.Td>
            <Table.Td>{rejectionReason(t, row.reason)}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </Stack>
  );
}

function rejectionReason(t: (key: string) => string, reason: string): string {
  if (!REASON_KEYS.has(reason)) return reason;
  const key = `channels.rejections.reason.${reason}`;
  const label = t(key);
  return label === key ? reason : label;
}
