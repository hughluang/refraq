"use client";

import { Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { listSemanticsChanges } from "@/features/sources/api/catalog";
import { semanticSourceLabel } from "@/features/sources/catalogLabel";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type HistoryTabProps = {
  objectId: string;
  listEnabled: boolean;
};

function formatValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function HistoryTab({ objectId, listEnabled }: HistoryTabProps) {
  const t = useTranslate();
  const fetchPage = useCallback(
    (query: PageQuery) => listSemanticsChanges(objectId, query),
    [objectId],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    enabled: listEnabled,
    resetDeps: [objectId],
  });

  if (!listEnabled) {
    return null;
  }

  return (
    <ListTable
      list={list}
      columnCount={5}
      minWidth={880}
      emptyMessage={t("catalog.history.empty")}
      head={
        <Table.Tr>
          <Table.Th>{t("catalog.history.field")}</Table.Th>
          <Table.Th>{t("catalog.history.old")}</Table.Th>
          <Table.Th>{t("catalog.history.new")}</Table.Th>
          <Table.Th>{t("catalog.history.source")}</Table.Th>
          <Table.Th>{t("catalog.history.at")}</Table.Th>
        </Table.Tr>
      }
    >
      {list.items.map((row) => (
        <Table.Tr key={row.id}>
          <Table.Td>
            {row.column_id ? `${row.field_name} (${row.column_id})` : row.field_name}
          </Table.Td>
          <Table.Td>{formatValue(row.old_value)}</Table.Td>
          <Table.Td>{formatValue(row.new_value)}</Table.Td>
          <Table.Td>{semanticSourceLabel(t, row.semantic_source)}</Table.Td>
          <Table.Td>
            <Instant value={row.created_at} />
          </Table.Td>
        </Table.Tr>
      ))}
    </ListTable>
  );
}
