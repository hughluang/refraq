"use client";

import { Skeleton, Stack, Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

import { ListPager } from "@/components/display/ListPager";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import type { ListState } from "@/lib/list-state";

const DEFAULT_MIN_WIDTH = 1080;
const SKELETON_ROWS = 8;

type ListTableProps = {
  state: ListState;
  columnCount: number;
  minWidth?: number;
  refreshing?: boolean;
  errorMessage?: string | null;
  errorRequestId?: string | null;
  onRetry?: () => void;
  emptyMessage?: string;
  noMatchMessage?: string;
  head: ReactNode;
  children?: ReactNode;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
};

function StatusRow({
  columnCount,
  children,
}: {
  columnCount: number;
  children: ReactNode;
}) {
  return (
    <Table.Tr>
      <Table.Td colSpan={columnCount}>{children}</Table.Td>
    </Table.Tr>
  );
}

function SkeletonRows({ columnCount }: { columnCount: number }) {
  return Array.from({ length: SKELETON_ROWS }, (_, row) => (
    <Table.Tr key={row}>
      {Array.from({ length: columnCount }, (_, col) => (
        <Table.Td key={col}>
          <Skeleton height={14} radius="sm" />
        </Table.Td>
      ))}
    </Table.Tr>
  ));
}

export function ListTable({
  state,
  columnCount,
  minWidth = DEFAULT_MIN_WIDTH,
  refreshing = false,
  errorMessage,
  errorRequestId,
  onRetry,
  emptyMessage,
  noMatchMessage,
  head,
  children,
  page,
  pageSize,
  total,
  onPageChange,
}: ListTableProps) {
  const t = useTranslate();
  const busy = state === "loading" || refreshing;
  let body: ReactNode;
  switch (state) {
    case "loading":
      body = <SkeletonRows columnCount={columnCount} />;
      break;
    case "error":
      body = (
        <StatusRow columnCount={columnCount}>
          <PageError
            message={errorMessage ?? ""}
            requestId={errorRequestId}
            onRetry={onRetry}
          />
        </StatusRow>
      );
      break;
    case "empty":
      body = (
        <StatusRow columnCount={columnCount}>
          <EmptyState message={emptyMessage ?? t("common.empty")} />
        </StatusRow>
      );
      break;
    case "no-match":
      body = (
        <StatusRow columnCount={columnCount}>
          <EmptyState message={noMatchMessage ?? t("common.noMatch")} />
        </StatusRow>
      );
      break;
    default:
      body = children;
  }

  return (
    <Stack gap="sm" flex={1} mih={0} style={{ minHeight: 0 }}>
      <Table.ScrollContainer
        minWidth={minWidth}
        maxHeight="100%"
        type="native"
        flex={1}
        mih={0}
        bd="1px solid light-dark(var(--mantine-color-gray-3), var(--mantine-color-dark-4))"
      >
        <Table
          striped
          highlightOnHover
          stickyHeader
          verticalSpacing="xs"
          horizontalSpacing="md"
        >
          <Table.Thead>{head}</Table.Thead>
          <Table.Tbody
            aria-busy={busy || undefined}
            style={refreshing ? { opacity: 0.6 } : undefined}
          >
            {body}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <ListPager
        page={page}
        pageSize={pageSize}
        total={total}
        onChange={onPageChange}
        disabled={busy}
      />
    </Stack>
  );
}
