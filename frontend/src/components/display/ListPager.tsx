"use client";

import { Group, Pagination, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { pageCountOf, showingRange } from "@/lib/pagination";

type ListPagerProps = {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
  disabled?: boolean;
};

export function ListPager({
  page,
  pageSize,
  total,
  onChange,
  disabled = false,
}: ListPagerProps) {
  const t = useTranslate();
  const { from, to } = showingRange(total, page, pageSize);
  const pageCount = pageCountOf(total, pageSize);

  return (
    <Group justify="space-between" mt="md" style={{ flexShrink: 0 }}>
      <Text size="sm" c="dimmed" aria-live="polite" aria-atomic="true">
        {t("common.showing", { from, to, total })}
      </Text>
      {pageCount > 1 ? (
        <Pagination
          value={page}
          onChange={onChange}
          total={pageCount}
          disabled={disabled}
        />
      ) : null}
    </Group>
  );
}
