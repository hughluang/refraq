"use client";

import { Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentTypeMappingOrigin } from "@/components/display/statusTone";
import { SelectField } from "@/components/form/SelectField";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

import { engineLabel } from "@/features/sources/engineLabel";

import { listTypeMappings, patchTypeMapping } from "./api";
import type { PatchableNormalizedType, TypeMapping } from "./types";

const PAGE_SIZE = 100;

const PATCHABLE: PatchableNormalizedType[] = [
  "string",
  "integer",
  "number",
  "decimal",
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

  const [busyId, setBusyId] = useState<string | null>(null);
  const query = useListQuery({
    filters: [
      { key: "engine", type: "select", defaultValue: "" },
      { key: "gaps", type: "select", defaultValue: "" },
    ],
  });
  const engine = query.select("engine");
  const gaps = query.select("gaps");

  const fetchPage = useCallback(
    (page: PageQuery) =>
      listTypeMappings({
        q: query.search || undefined,
        engine: engine || undefined,
        origin: gaps === "job" ? "job" : undefined,
        ...page,
      }),
    [query.search, engine, gaps],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, engine, gaps],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;

  const onPatch = async (row: TypeMapping, value: string | null) => {
    if (busyId === row.id) return;
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
        message: problemMessage(t, err, String(err)),
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageChrome
      title={t("typeMappings.title")}
      description={t("typeMappings.description")}
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("typeMappings.search")}
          filters={[
            {
              key: "engine",
              label: t("typeMappings.fields.engine"),
              options: ["postgresql", "mssql", "oracle"].map((value) => ({
                value,
                label: engineLabel(t, value),
              })),
            },
            {
              key: "gaps",
              label: t("typeMappings.fields.origin"),
              options: [
                { value: "job", label: t("typeMappings.list.onlyGaps") },
              ],
            },
          ]}
        />
      }
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("typeMappings.list.empty")}
        noMatchMessage={t("typeMappings.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("typeMappings.fields.engine")}</Table.Th>
            <Table.Th>{t("typeMappings.fields.nativeType")}</Table.Th>
            <Table.Th>{t("typeMappings.fields.normalizedType")}</Table.Th>
            <Table.Th>{t("typeMappings.fields.origin")}</Table.Th>
          </Table.Tr>
        }
      >
        {items.map((row) => {
          const isSeed = row.origin === "product";
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Text size="sm">{engineLabel(t, row.engine)}</Text>
              </Table.Td>
              <Table.Td>
                <Text ff="monospace" size="sm">
                  {row.native_type}
                </Text>
              </Table.Td>
              <Table.Td>
                <SelectField
                  editable={!isSeed && Boolean(canWrite?.can)}
                  size="xs"
                  w={160}
                  value={
                    row.normalized_type === "unknown"
                      ? null
                      : row.normalized_type
                  }
                  placeholder="unknown"
                  data={PATCHABLE}
                  onChange={(value) => void onPatch(row, value)}
                />
              </Table.Td>
              <Table.Td>
                <StatusBadge
                  size="xs"
                  tone={presentTypeMappingOrigin(row.origin).tone}
                  labelKey={presentTypeMappingOrigin(row.origin).labelKey}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </PageChrome>
  );
}
