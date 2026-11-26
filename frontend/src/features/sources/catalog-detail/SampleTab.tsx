"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Code,
  Drawer,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import { EmptyState } from "@/components/feedback/EmptyState";
import { MultiSelectField } from "@/components/form/MultiSelectField";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import {
  AlertIcon,
  CloseIcon,
  CopyIcon,
  EyeIcon,
  KeyIcon,
  PlusIcon,
  SortAscIcon,
  SortDescIcon,
  SortIcon,
} from "@/components/icons";
import {
  availableFilterOperators,
  filterOperatorLabelKey,
} from "@/lib/filterOperators";
import {
  binaryByteLength,
  cellExceedsDeclaredPrecision,
  formatSampleCell,
  isBinaryCell,
  isSampleFilterOp,
} from "@/features/sources/catalog-detail/sampleFilters";
import {
  DEFAULT_SAMPLE_LIMIT,
  useCatalogSample,
} from "@/features/sources/catalog-detail/useCatalogSample";
import type { CatalogObject, ColumnDeclaration } from "@/features/sources/types";
import { copyText } from "@/lib/copy-text";

type SampleTabProps = {
  object: CatalogObject;
};

export function SampleTab({ object }: SampleTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const sample = useCatalogSample(object);
  const {
    canSamplePending,
    canSample,
    forbidden,
    limit,
    setLimit,
    setOffset,
    filters,
    addFilter,
    removeFilter,
    updateFilter,
    clearFilters,
    selectedColumns,
    setSelectedColumns,
    includeSql,
    setIncludeSql,
    orderColumn,
    setOrderColumn,
    orderDirection,
    setOrderDirection,
    toggleSort,
    result,
    stale,
    unstableOrder,
    running,
    run,
  } = sample;

  const [inspectedRowIdx, setInspectedRowIdx] = useState<number | null>(null);

  useEffect(() => {
    setInspectedRowIdx(null);
  }, [result]);

  const presentColumns = useMemo(
    () => object.columns.filter((c) => c.is_present).map((c) => c.name),
    [object.columns],
  );

  const pkColumns = useMemo(() => {
    const presentSet = new Set(presentColumns);
    return (object.primary_key ?? []).filter((name) => presentSet.has(name));
  }, [object.primary_key, presentColumns]);

  const pkSet = useMemo(() => new Set(pkColumns), [pkColumns]);

  const columnOptions = useMemo(
    () => presentColumns.map((name) => ({ value: name, label: name })),
    [presentColumns],
  );

  const opOptions = useMemo(
    () =>
      availableFilterOperators([
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "is_null",
        "is_not_null",
      ]).map((op) => ({ value: op, label: t(filterOperatorLabelKey(op)) })),
    [t],
  );

  const declarationMap = useMemo(() => {
    const map = new Map<string, ColumnDeclaration>();
    for (const decl of result?.declarations ?? []) {
      map.set(decl.name, decl);
    }
    return map;
  }, [result?.declarations]);

  const handleCopy = async (text: string) => {
    try {
      await copyText(text);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  };

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

  const hasActiveFilter =
    filters.length > 1 ||
    filters.some((f) => f.column != null || f.value !== "");

  const inspectedRow =
    inspectedRowIdx != null && result ? result.rows[inspectedRowIdx] ?? null : null;
  const inspectedRowNumber =
    inspectedRowIdx != null && result ? result.offset + inspectedRowIdx + 1 : 0;

  const renderCellContent = (
    cell: unknown,
    declaration?: ColumnDeclaration,
    truncateText = true,
  ) => {
    if (cell === null || cell === undefined) {
      return (
        <Badge size="xs" variant="light" color="gray">
          {t("catalog.sample.nullBadge")}
        </Badge>
      );
    }
    if (cell === "") {
      return (
        <Badge size="xs" variant="outline" color="gray">
          {t("catalog.sample.emptyStringBadge")}
        </Badge>
      );
    }
    if (typeof cell === "boolean") {
      return (
        <Badge size="xs" variant="light" color={cell ? "teal" : "gray"}>
          {String(cell)}
        </Badge>
      );
    }
    if (isBinaryCell(cell)) {
      return (
        <Badge size="xs" variant="light" color="blue">
          {t("catalog.sample.binaryBadge", {
            bytes: binaryByteLength(cell.data),
          })}
        </Badge>
      );
    }
    const precisionExceeded = cellExceedsDeclaredPrecision(cell, declaration);
    if (typeof cell === "number") {
      return (
        <Group gap={4} wrap="nowrap">
          <Text size="xs" style={{ fontVariantNumeric: "tabular-nums" }}>
            {String(cell)}
          </Text>
          {precisionExceeded ? (
            <Tooltip label={t("catalog.sample.precision")}>
              <AlertIcon
                size={14}
                aria-label={t("catalog.sample.precision")}
                color="var(--refraq-tone-warning)"
              />
            </Tooltip>
          ) : null}
        </Group>
      );
    }
    if (typeof cell === "object") {
      const formatted = JSON.stringify(cell);
      return (
        <Code
          style={
            truncateText
              ? {
                  display: "inline-block",
                  maxWidth: 280,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  verticalAlign: "bottom",
                }
              : { whiteSpace: "pre-wrap", wordBreak: "break-word" }
          }
          title={truncateText ? formatted : undefined}
        >
          {formatted}
        </Code>
      );
    }
    const text = String(cell);
    return (
      <Group gap={4} wrap="nowrap">
        <Text
          size="xs"
          style={
            truncateText
              ? {
                  maxWidth: 320,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }
              : { whiteSpace: "pre-wrap", wordBreak: "break-word" }
          }
          title={truncateText ? text : undefined}
        >
          {text}
        </Text>
        {precisionExceeded ? (
          <Tooltip label={t("catalog.sample.precision")}>
            <AlertIcon
              size={14}
              aria-label={t("catalog.sample.precision")}
              color="var(--refraq-tone-warning)"
            />
          </Tooltip>
        ) : null}
      </Group>
    );
  };

  return (
    <Stack gap="sm">
      <Group align="flex-end" wrap="wrap">
        <NumberField
          editable
          label={t("catalog.sample.pageSize")}
          value={limit}
          onChange={(v) => {
            setLimit(typeof v === "number" ? v : DEFAULT_SAMPLE_LIMIT);
            setOffset(0);
          }}
          min={1}
          max={500}
          w={120}
        />
        <MultiSelectField
          editable
          label={t("catalog.sample.columnsLabel")}
          placeholder={t("catalog.sample.columnsAll", {
            count: presentColumns.length,
          })}
          data={columnOptions}
          value={selectedColumns}
          onChange={(cols) => {
            setSelectedColumns(cols);
            setOffset(0);
          }}
          searchable
          clearable
          w={260}
        />
        {pkColumns.length > 0 ? (
          <Button
            size="xs"
            variant="subtle"
            onClick={() => {
              setSelectedColumns(pkColumns);
              setOffset(0);
            }}
          >
            {t("catalog.sample.columnsPkOnly")}
          </Button>
        ) : null}
        {selectedColumns.length > 0 ? (
          <Button
            size="xs"
            variant="subtle"
            onClick={() => {
              setSelectedColumns([]);
              setOffset(0);
            }}
          >
            {t("catalog.sample.columnsReset")}
          </Button>
        ) : null}
        <SelectField
          editable
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
        <SelectField
          editable={orderColumn != null}
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
          w={130}
        />
        <Switch
          label={t("catalog.sample.showSql")}
          checked={includeSql}
          onChange={(e) => {
            setIncludeSql(e.currentTarget.checked);
            setOffset(0);
          }}
          pb={6}
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

      <Stack gap="xs">
        {filters.map((row, idx) => {
          const isUnary = row.op === "is_null" || row.op === "is_not_null";
          const needsValue = !isUnary && row.column != null;
          return (
            <Group key={row.id} align="flex-end" wrap="wrap">
              <SelectField
                editable
                label={idx === 0 ? t("catalog.sample.filterColumn") : undefined}
                aria-label={t("catalog.sample.filterColumn")}
                placeholder={t("catalog.sample.filterColumnPlaceholder")}
                data={columnOptions}
                value={row.column}
                onChange={(v) => {
                  updateFilter(row.id, { column: v });
                }}
                clearable
                searchable
                w={200}
              />
              <SelectField
                editable={row.column != null}
                label={idx === 0 ? t("catalog.sample.filterOp") : undefined}
                aria-label={t("catalog.sample.filterOp")}
                data={opOptions}
                value={row.op === "neq" ? "ne" : row.op}
                onChange={(v) => {
                  if (v == null || !isSampleFilterOp(v)) return;
                  updateFilter(row.id, { op: v });
                }}
                allowDeselect={false}
                w={180}
              />
              <TextField
                editable={needsValue}
                label={idx === 0 ? t("catalog.sample.filterValue") : undefined}
                aria-label={t("catalog.sample.filterValue")}
                placeholder={
                  row.op === "in" || row.op === "not_in" ? "a, b, c" : undefined
                }
                value={row.value}
                onChange={(e) => {
                  updateFilter(row.id, { value: e.currentTarget.value });
                }}
                w={row.op === "between" ? 130 : 200}
              />
              {row.op === "between" ? (
                <TextField
                  editable={needsValue}
                  label={idx === 0 ? t("entities.data.query.through") : undefined}
                  aria-label={t("entities.data.query.through")}
                  value={row.valueEnd ?? ""}
                  onChange={(e) => {
                    updateFilter(row.id, { valueEnd: e.currentTarget.value });
                  }}
                  w={130}
                />
              ) : null}
              {filters.length > 1 || row.column != null || row.value !== "" ? (
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  aria-label={t("catalog.sample.removeFilter")}
                  onClick={() => removeFilter(row.id)}
                  mb={4}
                >
                  <CloseIcon size={16} />
                </ActionIcon>
              ) : null}
            </Group>
          );
        })}
        <Group gap="xs">
          <Button
            size="xs"
            variant="subtle"
            leftSection={<PlusIcon size={14} />}
            onClick={addFilter}
          >
            {t("catalog.sample.addFilter")}
          </Button>
          {hasActiveFilter ? (
            <Button size="xs" variant="subtle" color="gray" onClick={clearFilters}>
              {t("catalog.sample.clearFilters")}
            </Button>
          ) : null}
        </Group>
      </Stack>

      {result?.sql ? (
        <Paper withBorder p="xs" radius="sm">
          <Group justify="space-between" mb={4}>
            <Text size="xs" fw={600} c="dimmed">
              {t("catalog.sample.compiledSql")}
            </Text>
            <ActionIcon
              size="sm"
              variant="subtle"
              aria-label={t("catalog.sample.copySql")}
              onClick={() => void handleCopy(result.sql ?? "")}
            >
              <CopyIcon size={14} />
            </ActionIcon>
          </Group>
          <Code block>{result.sql}</Code>
        </Paper>
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
                  from: result.rows.length === 0 ? 0 : result.offset + 1,
                  to: result.offset + result.rows.length,
                })}
              </Text>
              <Text size="sm" c="dimmed">
                {t("catalog.sample.duration", { ms: result.duration_ms })}
              </Text>
              {unstableOrder ? (
                <StatusBadge
                  tone="warning"
                  labelKey="catalog.sample.unstableOrder.badge"
                  explanation={t("catalog.sample.unstableOrder")}
                />
              ) : null}
              {stale ? (
                <StatusBadge
                  tone="warning"
                  labelKey="catalog.sample.outdated"
                  explanation={t("catalog.sample.stale")}
                />
              ) : null}
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
            <Table.ScrollContainer minWidth={600}>
              <Table striped highlightOnHover withTableBorder stickyHeader>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={64}>#</Table.Th>
                    {result.columns.map((col) => {
                      const isSorted = orderColumn === col;
                      return (
                        <Table.Th key={col}>
                          <UnstyledButton
                            aria-label={t("catalog.sample.sortBy", {
                              column: col,
                            })}
                            onClick={() => toggleSort(col)}
                          >
                            <Group gap={4} wrap="nowrap">
                              {pkSet.has(col) ? <KeyIcon size={14} /> : null}
                              <Text size="sm" fw={600}>
                                {col}
                              </Text>
                              {isSorted ? (
                                orderDirection === "asc" ? (
                                  <SortAscIcon size={14} />
                                ) : (
                                  <SortDescIcon size={14} />
                                )
                              ) : (
                                <SortIcon size={14} />
                              )}
                            </Group>
                          </UnstyledButton>
                        </Table.Th>
                      );
                    })}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {result.rows.map((row, rowIdx) => {
                    const displayIndex = result.offset + rowIdx + 1;
                    return (
                      <Table.Tr key={rowIdx}>
                        <Table.Td>
                          <Group gap={4} wrap="nowrap">
                            <Text
                              size="xs"
                              c="dimmed"
                              style={{ fontVariantNumeric: "tabular-nums" }}
                            >
                              {displayIndex}
                            </Text>
                            <ActionIcon
                              size="sm"
                              variant="subtle"
                              aria-label={t("catalog.sample.inspectRow", {
                                index: displayIndex,
                              })}
                              onClick={() => setInspectedRowIdx(rowIdx)}
                            >
                              <EyeIcon size={14} />
                            </ActionIcon>
                          </Group>
                        </Table.Td>
                        {row.map((cell, cellIdx) => {
                          const colName = result.columns[cellIdx];
                          const decl =
                            colName != null
                              ? declarationMap.get(colName)
                              : undefined;
                          return (
                            <Table.Td key={`${rowIdx}-${cellIdx}`}>
                              {renderCellContent(cell, decl, true)}
                            </Table.Td>
                          );
                        })}
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Stack>
      )}

      <Drawer
        opened={inspectedRow != null}
        onClose={() => setInspectedRowIdx(null)}
        position="right"
        size="md"
        title={t("catalog.sample.rowDrawerTitle", {
          index: inspectedRowNumber,
        })}
      >
        {inspectedRow != null && result != null ? (
          <Stack gap="sm">
            <Group justify="flex-end">
              <Button
                size="xs"
                variant="light"
                leftSection={<CopyIcon size={14} />}
                onClick={() => {
                  const payload = Object.fromEntries(
                    result.columns.map((col, idx) => [col, inspectedRow[idx]]),
                  );
                  void handleCopy(JSON.stringify(payload, null, 2));
                }}
              >
                {t("catalog.sample.copyRowJson")}
              </Button>
            </Group>
            <Stack gap="xs">
              {result.columns.map((col, idx) => {
                const cell = inspectedRow[idx];
                const decl = declarationMap.get(col);
                return (
                  <Paper key={col} withBorder p="xs" radius="sm">
                    <Group justify="space-between" mb={4}>
                      <Group gap={4}>
                        {pkSet.has(col) ? <KeyIcon size={14} /> : null}
                        <Text size="xs" fw={600}>
                          {col}
                        </Text>
                      </Group>
                      <ActionIcon
                        size="xs"
                        variant="subtle"
                        aria-label={t("catalog.sample.copyCell")}
                        onClick={() => void handleCopy(formatSampleCell(cell))}
                      >
                        <CopyIcon size={14} />
                      </ActionIcon>
                    </Group>
                    {renderCellContent(cell, decl, false)}
                  </Paper>
                );
              })}
            </Stack>
          </Stack>
        ) : null}
      </Drawer>
    </Stack>
  );
}
