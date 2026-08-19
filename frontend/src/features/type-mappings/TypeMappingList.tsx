"use client";

import { Badge, Checkbox, Group, Select, Table, Text, TextInput } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

import { listTypeMappings, patchTypeMapping } from "./api";
import type { PatchableNormalizedType, TypeMapping } from "./types";

const PAGE_SIZE = 100;

const PATCHABLE: PatchableNormalizedType[] = [
  "string",
  "integer",
  "number",
  "boolean",
  "date",
  "timestamp",
  "time",
  "interval",
  "binary",
  "json",
  "array",
];

export function TypeMappingList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.typeMappings,
    action: ModuleAction.edit,
  });

  const [q, setQ] = useState("");
  const [engine, setEngine] = useState<string | null>(null);
  const [onlyGaps, setOnlyGaps] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback(
    (query: PageQuery) =>
      listTypeMappings({
        q: q.trim() || undefined,
        engine: engine || undefined,
        origin: onlyGaps ? "job" : undefined,
        ...query,
      }),
    [q, engine, onlyGaps],
  );

  const { items, total, page, setPage, loading, error, reload, pageSize } =
    usePagedList({
      pageSize: PAGE_SIZE,
      fetch: fetchPage,
      resetDeps: [q, engine, onlyGaps],
      onError,
    });
  const filtered = q.trim() !== "" || Boolean(engine) || onlyGaps;
  const listPresentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: items.length,
    filtered,
  });

  const onPatch = async (row: TypeMapping, value: string | null) => {
    if (!value || value === row.normalized_type) return;
    setBusyId(row.id);
    try {
      await patchTypeMapping(row.id, {
        normalized_type: value as PatchableNormalizedType,
      });
      open?.({
        type: "success",
        message: t("typeMappings.update.success"),
      });
      await reload();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setBusyId(null);
    }
  };

  const originLabel = (origin: TypeMapping["origin"]) =>
    t(`typeMappings.origin.${origin}`);

  return (
    <PageChrome
      title={t("typeMappings.title")}
      description={t("typeMappings.description")}
    >
      <Group>
        <TextInput
          placeholder={t("typeMappings.search")}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          w={280}
        />
        <Select
          placeholder={t("typeMappings.fields.engine")}
          clearable
          value={engine}
          onChange={setEngine}
          data={[
            { value: "postgresql", label: "postgresql" },
            { value: "mssql", label: "mssql" },
            { value: "oracle", label: "oracle" },
          ]}
          w={180}
        />
        <Checkbox
          label={t("typeMappings.list.onlyGaps")}
          checked={onlyGaps}
          onChange={(e) => setOnlyGaps(e.currentTarget.checked)}
        />
      </Group>
      <ListTable
        state={listPresentation.state}
        columnCount={4}
        refreshing={listPresentation.refreshing}
        errorMessage={error}
        onRetry={() => void reload()}
        noMatchMessage={t("typeMappings.list.noMatch")}
        head={
          <Table.Tr>
            <Table.Th>{t("typeMappings.fields.engine")}</Table.Th>
            <Table.Th>{t("typeMappings.fields.nativeType")}</Table.Th>
            <Table.Th>{t("typeMappings.fields.normalizedType")}</Table.Th>
            <Table.Th>{t("typeMappings.fields.origin")}</Table.Th>
          </Table.Tr>
        }
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
      >
        {items.map((row) => {
          const isSeed = row.origin === "product";
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Text ff="monospace" size="sm">
                  {row.engine}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text ff="monospace" size="sm">
                  {row.native_type}
                </Text>
              </Table.Td>
              <Table.Td>
                {isSeed || !canWrite?.can ? (
                  <Text size="sm">{row.normalized_type}</Text>
                ) : (
                  <Select
                    size="xs"
                    w={160}
                    value={
                      row.normalized_type === "unknown"
                        ? null
                        : row.normalized_type
                    }
                    placeholder="unknown"
                    data={PATCHABLE}
                    disabled={busyId === row.id}
                    onChange={(value) => void onPatch(row, value)}
                  />
                )}
              </Table.Td>
              <Table.Td>
                <Badge
                  size="xs"
                  color={
                    row.origin === "product"
                      ? "gray"
                      : row.origin === "job"
                        ? "yellow"
                        : "blue"
                  }
                >
                  {originLabel(row.origin)}
                </Badge>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </PageChrome>
  );
}
