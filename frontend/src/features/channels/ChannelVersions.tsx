"use client";

import { Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
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

  return (
    <div className="channel-drawer-list">
      <ListTable
        list={list}
        columnCount={3}
        minWidth={640}
        emptyMessage={t("channels.versions.empty")}
        head={
          <Table.Tr>
            <Table.Th style={{ width: "5.5rem" }}>{t("channels.versions.number")}</Table.Th>
            <Table.Th>{t("channels.versions.publisher")}</Table.Th>
            <Table.Th style={{ width: "12rem" }}>{t("channels.versions.publishedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((version) => {
          const publisher = version.published_by_name;
          return (
            <Table.Tr key={version.number}>
              <Table.Td>{version.number}</Table.Td>
              <Table.Td>
                {publisher ? (
                  <RecordReference
                    name={publisher}
                    recordKey={version.published_by_user_id}
                    href={`/console/users/${version.published_by_user_id}`}
                  />
                ) : (
                  <Text size="sm">—</Text>
                )}
              </Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                <Instant value={version.published_at} />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </div>
  );
}
