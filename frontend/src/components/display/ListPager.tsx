"use client";

import { Group, Pagination, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

import { pageCountOf, showingRange } from "@/lib/pagination";

type ListPagerProps = {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
  disabled?: boolean;
  pageSizeControl?: ReactNode;
};

export function ListPager({
  page,
  pageSize,
  total,
  onChange,
  disabled = false,
  pageSizeControl,
}: ListPagerProps) {
  const t = useTranslate();
  const { from, to } = showingRange(total, page, pageSize);
  const pageCount = pageCountOf(total, pageSize);
  const range = (
    <Text size="sm" c="dimmed" aria-live="polite" aria-atomic="true">
      {t("common.showing", { from, to, total })}
    </Text>
  );

  return (
    <Group justify="space-between" mt="md" style={{ flexShrink: 0 }}>
      {pageSizeControl ? <Group gap="sm">{range}{pageSizeControl}</Group> : range}
      {pageCount > 1 ? (
        <Pagination
          value={page}
          onChange={onChange}
          total={pageCount}
          disabled={disabled}
          getControlProps={(control) => {
            if (control === "previous") return { "aria-label": t("common.prev") };
            if (control === "next") return { "aria-label": t("common.next") };
            return {};
          }}
        />
      ) : null}
    </Group>
  );
}
