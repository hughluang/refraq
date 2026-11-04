"use client";

import { Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import type { ChannelDatasetListItem } from "@/features/channels/types";
import { formatDatasetGigabytes } from "@/features/channel-dataset-usage/gigabytes";
import type { UsePagedListResult } from "@/hooks/usePagedList";

function runHref(row: ChannelDatasetListItem): string | undefined {
  if (row.channel_id == null) return undefined;
  return `/console/channels/${row.channel_id}/runs/${row.job_id}`;
}

export function DatasetUsageTable({
  list,
}: {
  list: UsePagedListResult<ChannelDatasetListItem>;
}) {
  const t = useTranslate();
  return (
    <ListTable
      list={list}
      columnCount={7}
      head={
        <Table.Tr>
          <Table.Th>{t("channelDatasetUsage.columns.channel")}</Table.Th>
          <Table.Th>{t("channelDatasetUsage.columns.node")}</Table.Th>
          <Table.Th>{t("channelDatasetUsage.columns.status")}</Table.Th>
          <Table.Th>{t("channelDatasetUsage.columns.size")}</Table.Th>
          <Table.Th>{t("channelDatasetUsage.columns.rows")}</Table.Th>
          <Table.Th>{t("channelDatasetUsage.columns.created")}</Table.Th>
          <Table.Th>{t("channelDatasetUsage.columns.expires")}</Table.Th>
        </Table.Tr>
      }
    >
      {list.items.map((row) => (
        <Table.Tr key={row.id}>
          <Table.Td>
            <RecordReference
              name={row.channel_name}
              recordKey={row.channel_id ?? ""}
              href={runHref(row)}
              copyable={false}
            />
          </Table.Td>
          <Table.Td>{row.node_name}</Table.Td>
          <Table.Td>{t(`channelDatasetUsage.status.${row.status}`)}</Table.Td>
          <Table.Td>{`${formatDatasetGigabytes(row.size_bytes)} GB`}</Table.Td>
          <Table.Td>{row.row_count}</Table.Td>
          <Table.Td>
            <Instant value={row.created_at} />
          </Table.Td>
          <Table.Td>
            <Instant value={row.expires_at} />
          </Table.Td>
        </Table.Tr>
      ))}
    </ListTable>
  );
}
