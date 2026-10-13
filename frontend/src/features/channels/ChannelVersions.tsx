"use client";

import { Table, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { Instant } from "@/components/display/Instant";
import { ListPager } from "@/components/display/ListPager";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { listVersions } from "@/features/channels/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ChannelVersions({
  channelId,
  reloadToken,
}: {
  channelId: string;
  reloadToken: number;
}) {
  const t = useTranslate();
  const fetchPage = useCallback(
    (query: PageQuery) => listVersions(channelId, query),
    [channelId],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [channelId, reloadToken],
  });
  const { items, presentation } = list;
  if (presentation.state === "loading") return null;
  if (presentation.state === "error") {
    return (
      <PageError
        message={list.error ?? ""}
        requestId={list.errorRequestId}
        onRetry={() => void list.reload()}
      />
    );
  }
  if (presentation.state === "empty") {
    return <EmptyState message={t("channels.versions.empty")} />;
  }
  return (
    <div className="channel-drawer-list">
      <div className="channel-drawer-list__scroll">
        <Table style={{ tableLayout: "fixed", width: "100%" }}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th style={{ width: "5.5rem" }}>{t("channels.versions.number")}</Table.Th>
            <Table.Th>{t("channels.versions.publisher")}</Table.Th>
            <Table.Th style={{ width: "12rem" }}>{t("channels.versions.publishedAt")}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((version) => {
            const publisher = version.published_by_name;
            return (
              <Table.Tr key={version.number}>
                <Table.Td>{version.number}</Table.Td>
                <Table.Td style={{ overflow: "hidden" }}>
                  {publisher ? (
                    <Tooltip label={publisher}>
                      <Text size="sm" truncate>
                        {publisher}
                      </Text>
                    </Tooltip>
                  ) : (
                    "—"
                  )}
                </Table.Td>
                <Table.Td style={{ whiteSpace: "nowrap" }}>
                  <Instant value={version.published_at} />
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
        </Table>
      </div>
      <ListPager
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onChange={list.setPage}
      />
    </div>
  );
}
