"use client";

import { Badge, Button, Code, Group, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useMemo, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar, type ListToolbarField } from "@/components/display/ListToolbar";
import { AgentIcon, UserIcon } from "@/components/icons";
import { listSemanticsChanges } from "@/features/sources/api/catalog";
import { objectCategoryLabel, semanticSourceLabel } from "@/features/sources/catalogLabel";
import type {
  CatalogColumn,
  ColumnSemantics,
  EnumCatalogEntry,
  SemanticsChange,
} from "@/features/sources/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { ListFilterSpec, ListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type HistoryTabProps = {
  objectId: string;
  listEnabled?: boolean;
  columns?: CatalogColumn[];
  onOpenColumn?: (columnId: string) => void;
};

const FIELD_LABEL_KEYS: Record<string, string> = {
  business_name: "catalog.semantics.businessName",
  business_description: "catalog.semantics.businessDescription",
  object_category: "catalog.semantics.category",
  grain_description: "catalog.semantics.grain",
  business_primary_key: "catalog.semantics.businessPrimaryKey",
  evidence_summary: "catalog.semantics.evidenceSummary",
  open_questions: "catalog.semantics.openQuestions",
  column_semantics: "catalog.columns.semanticsHeader",
};

function fieldLabel(t: (key: string) => string, fieldName: string): string {
  const key = FIELD_LABEL_KEYS[fieldName];
  if (key) return t(key);
  if (fieldName === "enum_catalog") return "Enum catalog";
  return fieldName;
}

function isEmptyScalar(value: unknown): boolean {
  return value == null || value === "";
}

function formatScalar(
  t: (key: string) => string,
  fieldName: string,
  value: unknown,
): string {
  if (isEmptyScalar(value)) return t("catalog.history.emptyValue");
  if (fieldName === "object_category" && typeof value === "string") {
    return objectCategoryLabel(t, value);
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isEnumCatalogArray(value: unknown): value is EnumCatalogEntry[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        "code" in item &&
        typeof (item as { code: unknown }).code === "string",
    )
  );
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function DiffCell({
  row,
  t,
}: {
  row: SemanticsChange;
  t: (key: string) => string;
}) {
  const { field_name: fieldName, old_value: oldValue, new_value: newValue } = row;

  // 1. enum_catalog diff by code
  if (
    fieldName === "enum_catalog" &&
    (oldValue == null || isEnumCatalogArray(oldValue)) &&
    (newValue == null || isEnumCatalogArray(newValue))
  ) {
    const oldList = (oldValue as EnumCatalogEntry[] | null) ?? [];
    const newList = (newValue as EnumCatalogEntry[] | null) ?? [];
    const oldMap = new Map(oldList.map((entry) => [entry.code, entry]));
    const newMap = new Map(newList.map((entry) => [entry.code, entry]));
    const lines: Array<{ key: string; prefix: "+" | "−" | "~"; text: string; tone: "teal" | "red" | "blue" }> = [];

    for (const entry of oldList) {
      const next = newMap.get(entry.code);
      if (!next) {
        lines.push({
          key: `rm:${entry.code}`,
          prefix: "−",
          text: `${entry.code}: ${entry.label}`,
          tone: "red",
        });
      } else if (
        next.label !== entry.label ||
        (next.description ?? null) !== (entry.description ?? null)
      ) {
        lines.push({
          key: `mod:${entry.code}`,
          prefix: "~",
          text: `${entry.code}: ${entry.label} → ${next.label}`,
          tone: "blue",
        });
      }
    }

    for (const entry of newList) {
      if (!oldMap.has(entry.code)) {
        lines.push({
          key: `add:${entry.code}`,
          prefix: "+",
          text: `${entry.code}: ${entry.label}`,
          tone: "teal",
        });
      }
    }

    if (lines.length === 0) {
      return (
        <Text size="xs" c="dimmed" fs="italic">
          {t("catalog.history.emptyValue")}
        </Text>
      );
    }

    return (
      <Stack gap={2}>
        {lines.map((line) => (
          <Text key={line.key} size="xs" c={line.tone} style={{ overflowWrap: "anywhere" }}>
            {line.prefix} {line.text}
          </Text>
        ))}
      </Stack>
    );
  }

  // 2. column_semantics composite object diff
  if (
    fieldName === "column_semantics" &&
    (oldValue == null || isPlainRecord(oldValue)) &&
    (newValue == null || isPlainRecord(newValue))
  ) {
    const oldObj = (oldValue as ColumnSemantics | null) ?? {};
    const newObj = (newValue as ColumnSemantics | null) ?? {};
    const keys = Array.from(
      new Set([...Object.keys(oldObj), ...Object.keys(newObj)]),
    ) as Array<keyof ColumnSemantics>;
    const changedKeys = keys.filter(
      (k) => (oldObj[k] ?? null) !== (newObj[k] ?? null),
    );

    if (changedKeys.length === 0) {
      return (
        <Text size="xs" c="dimmed" fs="italic">
          {t("catalog.history.emptyValue")}
        </Text>
      );
    }

    return (
      <Stack gap={2}>
        {changedKeys.map((key) => {
          const prev = oldObj[key];
          const next = newObj[key];
          return (
            <Group key={String(key)} gap={4} wrap="wrap">
              <Code fz="xs">{String(key)}</Code>
              <Text
                size="xs"
                c={isEmptyScalar(prev) ? "dimmed" : undefined}
                fs={isEmptyScalar(prev) ? "italic" : undefined}
              >
                {isEmptyScalar(prev) ? t("catalog.history.emptyValue") : String(prev)}
              </Text>
              <Text size="xs" c="dimmed" aria-hidden="true">
                →
              </Text>
              <Text
                size="xs"
                fw={500}
                c={isEmptyScalar(next) ? "dimmed" : undefined}
                fs={isEmptyScalar(next) ? "italic" : undefined}
              >
                {isEmptyScalar(next) ? t("catalog.history.emptyValue") : String(next)}
              </Text>
            </Group>
          );
        })}
      </Stack>
    );
  }

  // 3. String array diff (+ / −)
  if (
    (oldValue == null || isStringArray(oldValue)) &&
    (newValue == null || isStringArray(newValue)) &&
    (Array.isArray(oldValue) || Array.isArray(newValue))
  ) {
    const oldArr = (oldValue as string[] | null) ?? [];
    const newArr = (newValue as string[] | null) ?? [];
    const oldSet = new Set(oldArr);
    const newSet = new Set(newArr);
    const removed = oldArr.filter((item) => !newSet.has(item));
    const added = newArr.filter((item) => !oldSet.has(item));

    if (removed.length === 0 && added.length === 0) {
      return (
        <Text size="xs" c="dimmed" fs="italic">
          {t("catalog.history.emptyValue")}
        </Text>
      );
    }

    return (
      <Stack gap={2}>
        {removed.map((item, idx) => (
          <Text key={`rm:${idx}:${item}`} size="xs" c="red" style={{ overflowWrap: "anywhere" }}>
            − {item}
          </Text>
        ))}
        {added.map((item, idx) => (
          <Text key={`add:${idx}:${item}`} size="xs" c="teal" style={{ overflowWrap: "anywhere" }}>
            + {item}
          </Text>
        ))}
      </Stack>
    );
  }

  // 4. Scalar diff
  const oldEmpty = isEmptyScalar(oldValue);
  const newEmpty = isEmptyScalar(newValue);
  return (
    <Group gap={6} wrap="wrap" align="baseline">
      <Text
        size="xs"
        c={oldEmpty ? "dimmed" : undefined}
        fs={oldEmpty ? "italic" : undefined}
        style={{ overflowWrap: "anywhere" }}
      >
        {formatScalar(t, fieldName, oldValue)}
      </Text>
      <Text size="xs" c="dimmed" aria-hidden="true">
        →
      </Text>
      <Text
        size="xs"
        fw={500}
        c={newEmpty ? "dimmed" : undefined}
        fs={newEmpty ? "italic" : undefined}
        style={{ overflowWrap: "anywhere" }}
      >
        {formatScalar(t, fieldName, newValue)}
      </Text>
    </Group>
  );
}

export function HistoryTab({
  objectId,
  listEnabled = true,
  columns,
  onOpenColumn,
}: HistoryTabProps) {
  const t = useTranslate();
  const [scope, setScope] = useState<string>("");
  const [columnId, setColumnId] = useState<string>("");
  const [fieldName, setFieldName] = useState<string>("");
  const [semanticSource, setSemanticSource] = useState<string>("");

  const isFiltered = Boolean(scope || columnId || fieldName || semanticSource);

  const clearFilters = useCallback(() => {
    setScope("");
    setColumnId("");
    setFieldName("");
    setSemanticSource("");
  }, []);

  const fetchPage = useCallback(
    (query: PageQuery) =>
      listSemanticsChanges(objectId, {
        ...query,
        scope: (scope === "object" || scope === "column" ? scope : undefined),
        column_id: columnId || undefined,
        field_name: fieldName || undefined,
        semantic_source: semanticSource || undefined,
      }),
    [objectId, scope, columnId, fieldName, semanticSource],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    enabled: listEnabled,
    resetDeps: [objectId, scope, columnId, fieldName, semanticSource],
  });

  const filterSpecs: readonly ListFilterSpec[] = useMemo(
    () => [
      { key: "scope", type: "select", defaultValue: "" },
      ...(columns && columns.length > 0
        ? [{ key: "column_id", type: "select" as const, defaultValue: "" }]
        : []),
      { key: "field_name", type: "select", defaultValue: "" },
      { key: "semantic_source", type: "select", defaultValue: "" },
    ],
    [columns],
  );

  const filterFields: readonly ListToolbarField[] = useMemo(() => {
    const fields: ListToolbarField[] = [
      {
        key: "scope",
        label: t("catalog.history.scope"),
        options: [
          { value: "object", label: t("catalog.history.scopeObject") },
          { value: "column", label: t("catalog.history.scopeColumn") },
        ],
      },
    ];

    if (columns && columns.length > 0) {
      fields.push({
        key: "column_id",
        label: t("catalog.history.columnFilter"),
        options: columns.map((col) => ({
          value: col.id,
          label: col.business_name ? `${col.name} (${col.business_name})` : col.name,
        })),
      });
    }

    fields.push(
      {
        key: "field_name",
        label: t("catalog.history.fieldFilter"),
        options: [
          { value: "business_name", label: t("catalog.semantics.businessName") },
          { value: "business_description", label: t("catalog.semantics.businessDescription") },
          { value: "object_category", label: t("catalog.semantics.category") },
          { value: "grain_description", label: t("catalog.semantics.grain") },
          { value: "business_primary_key", label: t("catalog.semantics.businessPrimaryKey") },
          { value: "evidence_summary", label: t("catalog.semantics.evidenceSummary") },
          { value: "open_questions", label: t("catalog.semantics.openQuestions") },
          { value: "column_semantics", label: t("catalog.columns.semanticsHeader") },
          { value: "enum_catalog", label: "Enum catalog" },
        ],
      },
      {
        key: "semantic_source",
        label: t("catalog.history.sourceFilter"),
        options: [
          { value: "user_input", label: semanticSourceLabel(t, "user_input") },
          { value: "mcp", label: semanticSourceLabel(t, "mcp") },
        ],
      },
    );

    return fields;
  }, [columns, t]);

  const toolbarQuery: ListQuery = useMemo(
    () => ({
      searchEnabled: false,
      search: "",
      setSearch: () => {},
      filters: filterSpecs,
      select: (key: string) => {
        if (key === "scope") return scope;
        if (key === "column_id") return columnId;
        if (key === "field_name") return fieldName;
        if (key === "semantic_source") return semanticSource;
        return "";
      },
      multi: () => [],
      setFilter: (key: string, value: string | readonly string[]) => {
        const next = typeof value === "string" ? value : "";
        if (key === "scope") {
          setScope(next);
          if (next === "object") setColumnId("");
        } else if (key === "column_id") {
          setColumnId(next);
          if (next && scope === "object") setScope("");
        } else if (key === "field_name") {
          setFieldName(next);
        } else if (key === "semantic_source") {
          setSemanticSource(next);
        }
      },
      page: list.page,
      setPage: list.setPage,
      clear: clearFilters,
      isFiltered,
      initialSearch: "",
    }),
    [
      clearFilters,
      columnId,
      fieldName,
      filterSpecs,
      isFiltered,
      list.page,
      list.setPage,
      scope,
      semanticSource,
    ],
  );

  if (!listEnabled) {
    return null;
  }

  const columnNameById = new Map((columns ?? []).map((col) => [col.id, col.name]));
  const effectiveList =
    list.presentation.state === "empty" && isFiltered
      ? {
          ...list,
          presentation: { ...list.presentation, state: "no-match" as const },
        }
      : list;

  return (
    <Stack gap="sm" flex={1} mih={0} style={{ minHeight: 0 }}>
      <ListToolbar query={toolbarQuery} filters={filterFields} />
      <ListTable
        list={effectiveList}
        columnCount={5}
        minWidth={880}
        emptyMessage={t("catalog.history.empty")}
        noMatchMessage={t("catalog.history.noMatch")}
        onClearFilters={isFiltered ? clearFilters : undefined}
        head={
          <Table.Tr>
            <Table.Th>{t("catalog.history.at")}</Table.Th>
            <Table.Th>{t("catalog.history.target")}</Table.Th>
            <Table.Th>{t("catalog.history.field")}</Table.Th>
            <Table.Th>{t("catalog.history.diff")}</Table.Th>
            <Table.Th>{t("catalog.history.actor")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => {
          const colLabel = row.column_id
            ? row.column_name ?? columnNameById.get(row.column_id) ?? row.column_id
            : null;
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Instant value={row.created_at} />
              </Table.Td>
              <Table.Td>
                {row.column_id && colLabel ? (
                  onOpenColumn ? (
                    <Button
                      type="button"
                      size="compact-xs"
                      variant="light"
                      onClick={() => onOpenColumn(row.column_id!)}
                    >
                      {colLabel}
                    </Button>
                  ) : (
                    <Badge size="xs" variant="outline">
                      {colLabel}
                    </Badge>
                  )
                ) : (
                  <Badge size="xs" variant="light">
                    {t("catalog.history.targetObject")}
                  </Badge>
                )}
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  <Text size="xs" fw={500}>
                    {fieldLabel(t, row.field_name)}
                  </Text>
                  <Code fz="xs">{row.field_name}</Code>
                </Stack>
              </Table.Td>
              <Table.Td>
                <DiffCell row={row} t={t} />
              </Table.Td>
              <Table.Td>
                <Stack gap={2} align="flex-start">
                  <Badge
                    size="xs"
                    variant="light"
                    leftSection={
                      row.semantic_source === "mcp" ? (
                        <AgentIcon size={12} aria-hidden />
                      ) : (
                        <UserIcon size={12} aria-hidden />
                      )
                    }
                  >
                    {semanticSourceLabel(t, row.semantic_source)}
                  </Badge>
                  {row.actor_display_name ? (
                    <Text size="xs" c="dimmed">
                      {row.actor_display_name}
                    </Text>
                  ) : null}
                </Stack>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </Stack>
  );
}
