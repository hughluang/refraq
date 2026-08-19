"use client";

import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useMemo } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import {
  formatSampleCell,
  isSampleFilterOp,
} from "@/features/sources/catalog-detail/sampleFilters";
import {
  DEFAULT_SAMPLE_LIMIT,
  useCatalogSample,
} from "@/features/sources/catalog-detail/useCatalogSample";
import type { CatalogObject } from "@/features/sources/types";

type SampleTabProps = {
  object: CatalogObject;
};

export function SampleTab({ object }: SampleTabProps) {
  const t = useTranslate();
  const sample = useCatalogSample(object);
  const {
    canSamplePending,
    canSample,
    forbidden,
    limit,
    setLimit,
    setOffset,
    filter,
    setFilter,
    orderColumn,
    setOrderColumn,
    orderDirection,
    setOrderDirection,
    result,
    stale,
    unstableOrder,
    running,
    run,
  } = sample;

  const columnOptions = useMemo(
    () =>
      object.columns
        .filter((c) => c.is_present)
        .map((c) => ({ value: c.name, label: c.name })),
    [object.columns],
  );

  const opOptions = useMemo(
    () => [
      { value: "eq", label: t("catalog.sample.opEq") },
      { value: "neq", label: t("catalog.sample.opNeq") },
      { value: "contains", label: t("catalog.sample.opContains") },
      { value: "is_null", label: t("catalog.sample.opIsNull") },
    ],
    [t],
  );

  if (canSamplePending) {
    return <Loader size="sm" />;
  }

  if (!canSample || forbidden) {
    return (
      <Text size="sm" c="dimmed">
        {t("catalog.sample.forbidden")}
      </Text>
    );
  }

  const needsValue = filter.op !== "is_null" && filter.column != null;

  return (
    <Stack gap="sm">
      <Group align="flex-end" wrap="wrap">
        <NumberInput
          label={t("catalog.sample.pageSize")}
          value={limit}
          onChange={(v) => {
            setLimit(typeof v === "number" ? v : DEFAULT_SAMPLE_LIMIT);
            setOffset(0);
          }}
          min={1}
          max={500}
          w={140}
        />
        <Select
          label={t("catalog.sample.filterColumn")}
          placeholder={t("catalog.sample.filterColumnPlaceholder")}
          data={columnOptions}
          value={filter.column}
          onChange={(v) => {
            setFilter((prev) => ({ ...prev, column: v }));
            setOffset(0);
          }}
          clearable
          searchable
          w={200}
        />
        <Select
          label={t("catalog.sample.filterOp")}
          data={opOptions}
          value={filter.op}
          onChange={(v) => {
            if (v == null || !isSampleFilterOp(v)) return;
            setFilter((prev) => ({ ...prev, op: v }));
            setOffset(0);
          }}
          allowDeselect={false}
          w={140}
          disabled={!filter.column}
        />
        <TextInput
          label={t("catalog.sample.filterValue")}
          value={filter.value}
          onChange={(e) => {
            const value = e.currentTarget.value;
            setFilter((prev) => ({ ...prev, value }));
            setOffset(0);
          }}
          w={200}
          disabled={!needsValue}
        />
        <Select
          label={t("catalog.sample.orderColumn")}
          placeholder={t("catalog.sample.orderColumnPlaceholder")}
          data={columnOptions}
          value={orderColumn}
          onChange={(v) => {
            setOrderColumn(v);
            setOffset(0);
          }}
          clearable
          searchable
          w={200}
        />
        <Select
          label={t("catalog.sample.orderDirection")}
          data={[
            { value: "asc", label: t("catalog.sample.orderAsc") },
            { value: "desc", label: t("catalog.sample.orderDesc") },
          ]}
          value={orderDirection}
          onChange={(v) => {
            if (v === "asc" || v === "desc") {
              setOrderDirection(v);
              setOffset(0);
            }
          }}
          allowDeselect={false}
          w={120}
          disabled={!orderColumn}
        />
        <Button
          loading={running}
          onClick={() => {
            void run(0);
          }}
        >
          {result ? t("catalog.sample.reload") : t("catalog.sample.load")}
        </Button>
      </Group>

      {unstableOrder ? (
        <Alert color="yellow" variant="light">
          {t("catalog.sample.unstableOrder")}
        </Alert>
      ) : null}

      {stale ? (
        <Alert color="yellow" variant="light">
          {t("catalog.sample.stale")}
        </Alert>
      ) : null}

      {!result ? (
        <EmptyState message={t("catalog.sample.empty")} />
      ) : (
        <Stack gap="xs">
          <Group gap="sm" justify="space-between" wrap="wrap">
            <Group gap="sm">
              <Text size="sm" c="dimmed">
                {t("catalog.sample.rowCount", { count: result.rows.length })}
              </Text>
              <Text size="sm" c="dimmed">
                {t("catalog.sample.pageRange", {
                  from: result.offset + 1,
                  to: result.offset + result.rows.length,
                })}
              </Text>
              <Text size="sm" c="dimmed">
                {t("catalog.sample.duration", { ms: result.duration_ms })}
              </Text>
              {result.truncated ? (
                <Badge color="yellow">{t("catalog.sample.truncated")}</Badge>
              ) : null}
            </Group>
            <Group gap="xs">
              <Button
                size="xs"
                variant="default"
                disabled={running || result.offset <= 0}
                onClick={() => {
                  void run(Math.max(0, result.offset - result.limit));
                }}
              >
                {t("catalog.sample.prevPage")}
              </Button>
              <Button
                size="xs"
                variant="default"
                disabled={running || !result.has_more}
                onClick={() => {
                  void run(result.offset + result.limit);
                }}
              >
                {t("catalog.sample.nextPage")}
              </Button>
            </Group>
          </Group>
          {result.rows.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("catalog.sample.zeroRows")}
            </Text>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <Table striped highlightOnHover withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    {result.columns.map((col) => (
                      <Table.Th key={col}>
                        <Text size="sm">{col}</Text>
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {result.rows.map((row, rowIdx) => (
                    <Table.Tr key={rowIdx}>
                      {row.map((cell, cellIdx) => (
                        <Table.Td key={`${rowIdx}-${cellIdx}`}>
                          <Text size="xs" style={{ whiteSpace: "pre-wrap" }}>
                            {formatSampleCell(cell)}
                          </Text>
                        </Table.Td>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </div>
          )}
        </Stack>
      )}
    </Stack>
  );
}
