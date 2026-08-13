"use client";

import { Badge, Checkbox, Group, Select, Table, Text, TextInput } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { ApiError } from "@/lib/api";

import { listTypeMappings, patchTypeMapping } from "./api";
import type { PatchableNormalizedType, TypeMapping } from "./types";

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

  const [items, setItems] = useState<TypeMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [engine, setEngine] = useState<string | null>(null);
  const [onlyGaps, setOnlyGaps] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTypeMappings({
        q: q.trim() || undefined,
        engine: engine || undefined,
        origin: onlyGaps ? "job" : undefined,
        limit: 500,
      });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [q, engine, onlyGaps]);

  useEffect(() => {
    void load();
  }, [load]);

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
      await load();
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
      {error ? (
        <PageError message={error} onRetry={() => void load()} />
      ) : (
        <>
          <Group mb="md">
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
          {loading ? (
            <PageLoader />
          ) : items.length === 0 ? (
            <EmptyState />
          ) : (
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("typeMappings.fields.engine")}</Table.Th>
                  <Table.Th>{t("typeMappings.fields.nativeType")}</Table.Th>
                  <Table.Th>{t("typeMappings.fields.normalizedType")}</Table.Th>
                  <Table.Th>{t("typeMappings.fields.origin")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
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
              </Table.Tbody>
            </Table>
          )}
        </>
      )}
    </PageChrome>
  );
}
