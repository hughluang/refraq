"use client";

import { Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { listSemanticsChanges } from "@/features/sources/api/catalog";
import type { SemanticsChange } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

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
  const [items, setItems] = useState<SemanticsChange[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!listEnabled) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void listSemanticsChanges(objectId)
      .then((page) => {
        if (!cancelled) setItems(page.items);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [objectId, listEnabled]);

  if (!listEnabled) {
    return null;
  }
  if (loading) {
    return <PageBodySkeleton />;
  }
  if (error) {
    return <PageError message={error} />;
  }
  if (items.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        {t("catalog.history.empty")}
      </Text>
    );
  }

  return (
    <Table striped highlightOnHover>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t("catalog.history.field")}</Table.Th>
          <Table.Th>{t("catalog.history.old")}</Table.Th>
          <Table.Th>{t("catalog.history.new")}</Table.Th>
          <Table.Th>{t("catalog.history.source")}</Table.Th>
          <Table.Th>{t("catalog.history.at")}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              {row.column_id
                ? `${row.field_name} (${row.column_id})`
                : row.field_name}
            </Table.Td>
            <Table.Td>{formatValue(row.old_value)}</Table.Td>
            <Table.Td>{formatValue(row.new_value)}</Table.Td>
            <Table.Td>{row.semantic_source}</Table.Td>
            <Table.Td>{row.created_at}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
