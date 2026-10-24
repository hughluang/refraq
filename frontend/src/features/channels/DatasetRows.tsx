"use client";

import { Button, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { listDatasetRows } from "@/features/channels/api";
import {
  datasetRowLimit,
  rowsInsideWindow,
  type DatasetColumn,
  type DatasetReference,
} from "@/features/channels/datasetView";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";

const REASONS = ["not_found", "expired", "lost", "foreign_run"] as const;

export function DatasetCard({
  channelId,
  jobId,
  dataset,
}: {
  channelId: string;
  jobId: string;
  dataset: DatasetReference;
}) {
  const t = useTranslate();
  const [open, setOpen] = useState(false);
  return (
    <Stack gap={4}>
      <Text size="xs" fw={600}>
        {t("channels.run.dataset.reference")}
      </Text>
      <Text size="xs">{dataset.dataset_id}</Text>
      <Text size="xs" c="dimmed">
        {t("channels.run.dataset.count", { count: dataset.count })}
      </Text>
      <Text size="xs">
        {dataset.columns.map((column) => `${column.name} (${column.type})`).join(", ")}
      </Text>
      {open ? (
        <DatasetRowTable
          key={`${dataset.dataset_id}:${dataset.count}`}
          channelId={channelId}
          jobId={jobId}
          datasetId={dataset.dataset_id}
          afterOrd={0}
          endOrd={dataset.count}
          columns={dataset.columns}
        />
      ) : (
        <Button size="compact-xs" variant="default" onClick={() => setOpen(true)}>
          {t("channels.run.dataset.showRows")}
        </Button>
      )}
    </Stack>
  );
}

export function DatasetRowTable({
  channelId,
  jobId,
  datasetId,
  afterOrd,
  endOrd,
  columns,
  hideOrd = false,
  onHeaderPick,
  onCellPick,
}: {
  channelId: string;
  jobId: string;
  datasetId: string;
  afterOrd: number;
  endOrd: number;
  columns: readonly DatasetColumn[];
  /** Output View hides the storage ordinal. Batch windows keep it. */
  hideOrd?: boolean;
  onHeaderPick?: (column: string) => void;
  onCellPick?: (column: string, rowIndex: number) => void;
}) {
  const t = useTranslate();
  const span = Math.max(0, endOrd - afterOrd);
  const pageSize = datasetRowLimit(afterOrd, endOrd) ?? 1;
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [reason, setReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setReason(null);
    const cursor = afterOrd + (page - 1) * pageSize;
    const limit = datasetRowLimit(cursor, endOrd);
    if (limit == null) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void readPage(channelId, jobId, datasetId, cursor, limit, endOrd)
      .then((result) => {
        if (cancelled) return;
        setRows(result.rows);
        setReason(result.reason);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, jobId, datasetId, afterOrd, endOrd, page, pageSize, reloadToken]);

  if (reason && reason !== "error") {
    const known = REASONS.find((item) => item === reason);
    return (
      <Text size="xs" role="status">
        {known ? t(`channels.run.dataset.reason.${known}`) : reason}
      </Text>
    );
  }

  const error = reason === "error" ? t("channels.run.rowsFailed") : null;
  const list = {
    presentation: listPresentationOf({
      loading,
      error,
      total: span,
      itemCount: rows.length,
      filtered: false,
    }),
    error,
    errorRequestId: null,
    reload: () => setReloadToken((token) => token + 1),
    page,
    setPage,
    pageSize,
    total: span,
  };
  const headColumns = hideOrd ? columns.length : columns.length + 1;
  return (
    <ListTable
      embedded
      list={list}
      columnCount={headColumns}
      minWidth={360}
      head={
        <Table.Tr>
          {hideOrd ? null : <Table.Th>_ord</Table.Th>}
          {columns.map((column) => (
            <Table.Th key={column.name}>
              {onHeaderPick ? (
                <button type="button" className="channel-view-pick" onClick={() => onHeaderPick(column.name)}>
                  {column.name}
                </button>
              ) : (
                column.name
              )}
            </Table.Th>
          ))}
        </Table.Tr>
      }
    >
      {rows.map((row, rowIndex) => (
        <Table.Tr key={String(row._ord)}>
          {hideOrd ? null : <Table.Td>{String(row._ord)}</Table.Td>}
          {columns.map((column) => (
            <Table.Td key={column.name}>
              {onCellPick ? (
                <button
                  type="button"
                  className="channel-view-pick"
                  onClick={() => onCellPick(column.name, rowIndex)}
                >
                  {cellText(row[column.name])}
                </button>
              ) : (
                cellText(row[column.name])
              )}
            </Table.Td>
          ))}
        </Table.Tr>
      ))}
    </ListTable>
  );
}

async function readPage(
  channelId: string,
  jobId: string,
  datasetId: string,
  afterOrd: number,
  limit: number,
  endOrd: number,
): Promise<{ rows: Record<string, unknown>[]; reason: string | null }> {
  try {
    const page = await listDatasetRows(channelId, jobId, datasetId, {
      after_ord: afterOrd,
      limit,
    });
    const visible = rowsInsideWindow(
      page.items.flatMap((item) => {
        const ord = item._ord;
        if (typeof ord !== "number") return [];
        return [{ ...item, _ord: ord }];
      }),
      endOrd,
    );
    return { rows: visible, reason: null };
  } catch (error: unknown) {
    const unavailable =
      error instanceof ApiError && error.code === "CHANNEL_DATASET_UNAVAILABLE"
        ? String(error.extensions.reason ?? "not_found")
        : null;
    return { rows: [], reason: unavailable ?? "error" };
  }
}

function cellText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
