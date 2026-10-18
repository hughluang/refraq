"use client";

import { Button, Skeleton, Stack, Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState, type ReactNode } from "react";

import { ListPager } from "@/components/display/ListPager";
import { FEEDBACK_DELAY_MS, TABLE_DENSITY } from "@/theme";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import type { ListPresentation } from "@/lib/list-state";

const DEFAULT_MIN_WIDTH = 1080;
const SKELETON_ROWS = 8;

/** Session fields `ListTable` binds to status, retry, and the pager. */
export type ListTableList = {
  presentation: ListPresentation;
  error: string | null;
  errorRequestId: string | null;
  reload: () => void | Promise<void>;
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  total: number;
};

type ListTableProps = {
  list: ListTableList;
  columnCount: number;
  minWidth?: number;
  /**
   * Size to the rows. Use inside a scrolling tab, drawer section, or form page.
   * Page lists omit this and fill the remaining frame.
   */
  embedded?: boolean;
  emptyMessage?: string;
  /** Primary action on the empty row, such as create when it is permitted. */
  emptyAction?: ReactNode;
  noMatchMessage?: string;
  /** No-match row offers Clear filters when this is set. */
  onClearFilters?: () => void;
  /** Replaces the clear-filters control on the no-match row. */
  noMatchAction?: ReactNode;
  head: ReactNode;
  children?: ReactNode;
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
  list,
  columnCount,
  minWidth = DEFAULT_MIN_WIDTH,
  embedded = false,
  emptyMessage,
  emptyAction,
  noMatchMessage,
  onClearFilters,
  noMatchAction,
  head,
  children,
}: ListTableProps) {
  const t = useTranslate();
  const { state, refreshing } = list.presentation;
  const busy = state === "loading" || refreshing;
  const [dimmed, setDimmed] = useState(false);
  useEffect(() => {
    if (!refreshing) {
      setDimmed(false);
      return;
    }
    const timer = window.setTimeout(() => setDimmed(true), FEEDBACK_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [refreshing]);
  let body: ReactNode;
  switch (state) {
    case "loading":
      body = <SkeletonRows columnCount={columnCount} />;
      break;
    case "error":
      body = (
        <StatusRow columnCount={columnCount}>
          <PageError
            message={list.error ?? ""}
            requestId={list.errorRequestId}
            onRetry={() => void list.reload()}
          />
        </StatusRow>
      );
      break;
    case "empty":
      body = (
        <StatusRow columnCount={columnCount}>
          <EmptyState message={emptyMessage ?? t("common.empty")} action={emptyAction} />
        </StatusRow>
      );
      break;
    case "no-match":
      body = (
        <StatusRow columnCount={columnCount}>
          <EmptyState
            message={noMatchMessage ?? t("common.noMatch")}
            action={
              noMatchAction ??
              (onClearFilters ? (
                <Button type="button" variant="subtle" size="xs" onClick={onClearFilters}>
                  {t("common.filters.clear")}
                </Button>
              ) : undefined)
            }
          />
        </StatusRow>
      );
      break;
    default:
      body = children;
  }

  return (
    <Stack
      gap="sm"
      flex={embedded ? undefined : 1}
      mih={embedded ? undefined : 0}
      style={embedded ? undefined : { minHeight: 0 }}
    >
      <Table.ScrollContainer
        minWidth={minWidth}
        maxHeight={embedded ? undefined : "100%"}
        type="native"
        flex={embedded ? undefined : 1}
        mih={embedded ? undefined : 0}
        bd="1px solid var(--refraq-tone-neutral-border)"
      >
        <Table
          striped
          highlightOnHover
          stickyHeader
          verticalSpacing={TABLE_DENSITY.verticalSpacing}
          horizontalSpacing={TABLE_DENSITY.horizontalSpacing}
        >
          <Table.Thead>{head}</Table.Thead>
          <Table.Tbody
            aria-busy={busy || undefined}
            style={dimmed ? { opacity: 0.6 } : undefined}
          >
            {body}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <ListPager
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onChange={list.setPage}
        disabled={busy}
      />
    </Stack>
  );
}
