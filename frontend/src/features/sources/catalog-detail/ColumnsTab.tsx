"use client";

import {
  Badge,
  Button,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState, Fragment } from "react";

import { patchColumnSemanticsBatch } from "@/features/sources/api";
import type {
  CatalogObject,
  ColumnSemantics,
  EnumCatalogEntry,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

const PAGE_SIZE = 50;

type ColumnDraft = {
  business_name: string;
  business_description: string;
  column_semantics: ColumnSemantics;
  enum_catalog: EnumCatalogEntry[];
};

type ColumnFilter =
  | "all"
  | "empty"
  | "filled"
  | "enum"
  | "pk"
  | "fk"
  | "absent";

type ColumnsTabProps = {
  object: CatalogObject;
  writable: boolean;
  onSaved: (object: CatalogObject) => void;
};

function draftFromColumn(col: CatalogObject["columns"][number]): ColumnDraft {
  return {
    business_name: col.business_name ?? "",
    business_description: col.business_description ?? "",
    column_semantics: {
      semantic_type: col.column_semantics?.semantic_type ?? "",
      value_pattern: col.column_semantics?.value_pattern ?? "",
      unit: col.column_semantics?.unit ?? "",
    },
    enum_catalog: (col.enum_catalog ?? []).map((e) => ({
      code: e.code,
      label: e.label,
      description: e.description ?? "",
    })),
  };
}

function draftsEqual(a: ColumnDraft, b: ColumnDraft): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function normalizeForSave(draft: ColumnDraft) {
  const semanticType = draft.column_semantics.semantic_type?.trim() || null;
  const valuePattern = draft.column_semantics.value_pattern?.trim() || null;
  const unit = draft.column_semantics.unit?.trim() || null;
  const hasSemantics = Boolean(semanticType || valuePattern || unit);
  return {
    business_name: draft.business_name,
    business_description: draft.business_description,
    column_semantics: hasSemantics
      ? {
          semantic_type: semanticType,
          value_pattern: valuePattern,
          unit,
        }
      : null,
    enum_catalog: draft.enum_catalog
      .filter((e) => e.code.trim())
      .map((e) => ({
        code: e.code.trim(),
        label: e.label.trim() || e.code.trim(),
        description: e.description?.trim() || null,
      })),
  };
}

export function ColumnsTab({
  object,
  writable,
  onSaved,
}: ColumnsTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [drafts, setDrafts] = useState<Record<string, ColumnDraft>>({});
  const [baseline, setBaseline] = useState<Record<string, ColumnDraft>>({});
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<ColumnFilter>("all");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next: Record<string, ColumnDraft> = {};
    for (const col of object.columns) {
      next[col.id] = draftFromColumn(col);
    }
    setDrafts(next);
    setBaseline(next);
    setExpanded({});
    setPage(1);
  }, [object.id, object.columns]);

  const pkSet = useMemo(
    () => new Set(object.primary_key ?? []),
    [object.primary_key],
  );
  const fkSet = useMemo(() => {
    const set = new Set<string>();
    for (const fk of object.foreign_keys ?? []) {
      for (const name of fk.columns) set.add(name);
    }
    return set;
  }, [object.foreign_keys]);

  const dirtyIds = useMemo(() => {
    return object.columns
      .filter((col) => {
        const draft = drafts[col.id];
        const base = baseline[col.id];
        if (!draft || !base) return false;
        return !draftsEqual(draft, base);
      })
      .map((c) => c.id);
  }, [object.columns, drafts, baseline]);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    return object.columns.filter((col) => {
      const draft = drafts[col.id] ?? draftFromColumn(col);
      if (query) {
        const hay = `${col.name} ${draft.business_name} ${col.locator_key}`.toLowerCase();
        if (!hay.includes(query)) return false;
      }
      const hasName = Boolean(draft.business_name.trim());
      const hasDesc = Boolean(draft.business_description.trim());
      const hasEnum = draft.enum_catalog.length > 0;
      switch (filter) {
        case "empty":
          return !(hasName && hasDesc);
        case "filled":
          return hasName && hasDesc;
        case "enum":
          return hasEnum;
        case "pk":
          return pkSet.has(col.name);
        case "fk":
          return fkSet.has(col.name);
        case "absent":
          return !col.is_present;
        default:
          return true;
      }
    });
  }, [object.columns, drafts, q, filter, pkSet, fkSet]);

  useEffect(() => {
    setPage(1);
  }, [q, filter]);

  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const updateDraft = (columnId: string, patch: Partial<ColumnDraft>) => {
    setDrafts((prev) => ({
      ...prev,
      [columnId]: {
        ...(prev[columnId] ??
          draftFromColumn(object.columns.find((c) => c.id === columnId)!)),
        ...patch,
      },
    }));
  };

  const saveDirty = async () => {
    if (!dirtyIds.length) return;
    setSaving(true);
    try {
      const columns = dirtyIds.map((id) => {
        const col = object.columns.find((c) => c.id === id)!;
        const draft = drafts[id];
        const payload = normalizeForSave(draft);
        return {
          column_name: col.name,
          ...payload,
        };
      });
      const data = await patchColumnSemanticsBatch(object.id, columns);
      onSaved(data.object);
      open?.({ type: "success", message: t("catalog.semantics.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="sm">
      <Group align="flex-end" wrap="wrap">
        <TextInput
          label={t("catalog.columns.search")}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          w={240}
        />
        <Select
          label={t("catalog.columns.filter")}
          value={filter}
          onChange={(v) => setFilter((v as ColumnFilter) || "all")}
          data={[
            { value: "all", label: t("catalog.columns.filterAll") },
            { value: "empty", label: t("catalog.columns.filterEmpty") },
            { value: "filled", label: t("catalog.columns.filterFilled") },
            { value: "enum", label: t("catalog.columns.filterEnum") },
            { value: "pk", label: t("catalog.columns.filterPk") },
            { value: "fk", label: t("catalog.columns.filterFk") },
            { value: "absent", label: t("catalog.columns.filterAbsent") },
          ]}
          w={200}
        />
        {writable && dirtyIds.length > 0 ? (
          <Group gap="xs">
            <Text size="sm" c="dimmed">
              {t("catalog.columns.dirtyHint", { count: dirtyIds.length })}
            </Text>
            <Button loading={saving} onClick={() => void saveDirty()}>
              {t("catalog.columns.saveDirty", { count: dirtyIds.length })}
            </Button>
          </Group>
        ) : null}
      </Group>

      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>{t("catalog.fields.column")}</Table.Th>
            <Table.Th>{t("catalog.fields.dataType")}</Table.Th>
            <Table.Th>{t("catalog.fields.nullable")}</Table.Th>
            <Table.Th>{t("catalog.semantics.businessName")}</Table.Th>
            <Table.Th>{t("catalog.semantics.businessDescription")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {pageItems.map((col) => {
            const draft = drafts[col.id] ?? draftFromColumn(col);
            const isDirty = dirtyIds.includes(col.id);
            const isOpen = Boolean(expanded[col.id]);
            return (
              <Fragment key={col.id}>
                <Table.Tr>
                  <Table.Td>{col.ordinal}</Table.Td>
                  <Table.Td>
                    <Stack gap={2}>
                      <Group gap={6}>
                        <Text size="sm" fw={isDirty ? 600 : 400}>
                          {col.name}
                        </Text>
                        {pkSet.has(col.name) ? (
                          <Badge size="xs">PK</Badge>
                        ) : null}
                        {fkSet.has(col.name) ? (
                          <Badge size="xs" color="grape">
                            FK
                          </Badge>
                        ) : null}
                        {!col.is_present ? (
                          <Badge size="xs" color="gray">
                            {t("catalog.fields.absentValue")}
                          </Badge>
                        ) : null}
                        {isDirty ? (
                          <Badge size="xs" color="yellow">
                            *
                          </Badge>
                        ) : null}
                      </Group>
                      <Text size="xs" c="dimmed">
                        {col.comment ?? col.locator_key}
                      </Text>
                    </Stack>
                  </Table.Td>
                  <Table.Td>{col.data_type}</Table.Td>
                  <Table.Td>
                    {col.nullable
                      ? t("catalog.fields.yes")
                      : t("catalog.fields.no")}
                  </Table.Td>
                  <Table.Td>
                    {writable ? (
                      <TextInput
                        size="xs"
                        value={draft.business_name}
                        onChange={(e) =>
                          updateDraft(col.id, {
                            business_name: e.currentTarget.value,
                          })
                        }
                      />
                    ) : (
                      col.business_name ?? "—"
                    )}
                  </Table.Td>
                  <Table.Td>
                    {writable ? (
                      <TextInput
                        size="xs"
                        value={draft.business_description}
                        onChange={(e) =>
                          updateDraft(col.id, {
                            business_description: e.currentTarget.value,
                          })
                        }
                      />
                    ) : (
                      col.business_description ?? "—"
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() =>
                        setExpanded((prev) => ({
                          ...prev,
                          [col.id]: !prev[col.id],
                        }))
                      }
                    >
                      {isOpen
                        ? t("catalog.columns.collapse")
                        : t("catalog.columns.expand")}
                    </Button>
                  </Table.Td>
                </Table.Tr>
                {isOpen ? (
                  <Table.Tr>
                    <Table.Td colSpan={7}>
                      <Stack gap="xs" p="sm">
                        <Group grow>
                          <TextInput
                            label={t("catalog.semantics.semanticType")}
                            size="xs"
                            value={draft.column_semantics.semantic_type ?? ""}
                            disabled={!writable}
                            onChange={(e) =>
                              updateDraft(col.id, {
                                column_semantics: {
                                  ...draft.column_semantics,
                                  semantic_type: e.currentTarget.value,
                                },
                              })
                            }
                          />
                          <TextInput
                            label={t("catalog.semantics.valuePattern")}
                            size="xs"
                            value={draft.column_semantics.value_pattern ?? ""}
                            disabled={!writable}
                            onChange={(e) =>
                              updateDraft(col.id, {
                                column_semantics: {
                                  ...draft.column_semantics,
                                  value_pattern: e.currentTarget.value,
                                },
                              })
                            }
                          />
                          <TextInput
                            label={t("catalog.semantics.unit")}
                            size="xs"
                            value={draft.column_semantics.unit ?? ""}
                            disabled={!writable}
                            onChange={(e) =>
                              updateDraft(col.id, {
                                column_semantics: {
                                  ...draft.column_semantics,
                                  unit: e.currentTarget.value,
                                },
                              })
                            }
                          />
                        </Group>
                        <Text size="sm" fw={500}>
                          {t("catalog.columns.enumTitle")}
                        </Text>
                        {draft.enum_catalog.map((entry, idx) => (
                          <Group key={`${col.id}-enum-${idx}`} align="flex-end">
                            <TextInput
                              label={t("catalog.columns.enumCode")}
                              size="xs"
                              value={entry.code}
                              disabled={!writable}
                              onChange={(e) => {
                                const next = [...draft.enum_catalog];
                                next[idx] = {
                                  ...entry,
                                  code: e.currentTarget.value,
                                };
                                updateDraft(col.id, { enum_catalog: next });
                              }}
                            />
                            <TextInput
                              label={t("catalog.columns.enumLabel")}
                              size="xs"
                              value={entry.label}
                              disabled={!writable}
                              onChange={(e) => {
                                const next = [...draft.enum_catalog];
                                next[idx] = {
                                  ...entry,
                                  label: e.currentTarget.value,
                                };
                                updateDraft(col.id, { enum_catalog: next });
                              }}
                            />
                            <Textarea
                              label={t("catalog.columns.enumDescription")}
                              size="xs"
                              value={entry.description ?? ""}
                              disabled={!writable}
                              minRows={1}
                              onChange={(e) => {
                                const next = [...draft.enum_catalog];
                                next[idx] = {
                                  ...entry,
                                  description: e.currentTarget.value,
                                };
                                updateDraft(col.id, { enum_catalog: next });
                              }}
                            />
                            {writable ? (
                              <Button
                                size="xs"
                                variant="subtle"
                                color="red"
                                onClick={() => {
                                  const next = draft.enum_catalog.filter(
                                    (_, i) => i !== idx,
                                  );
                                  updateDraft(col.id, { enum_catalog: next });
                                }}
                              >
                                {t("catalog.columns.enumRemove")}
                              </Button>
                            ) : null}
                          </Group>
                        ))}
                        {writable ? (
                          <Button
                            size="xs"
                            variant="light"
                            w="fit-content"
                            onClick={() =>
                              updateDraft(col.id, {
                                enum_catalog: [
                                  ...draft.enum_catalog,
                                  { code: "", label: "", description: "" },
                                ],
                              })
                            }
                          >
                            {t("catalog.columns.enumAdd")}
                          </Button>
                        ) : null}
                        {col.default_value ? (
                          <Text size="xs" c="dimmed">
                            {t("catalog.structure.default")}: {col.default_value}
                          </Text>
                        ) : null}
                        {col.semantic_source ? (
                          <Text size="xs" c="dimmed">
                            {t("catalog.semantics.provenance")}:{" "}
                            {col.semantic_source}
                          </Text>
                        ) : null}
                      </Stack>
                    </Table.Td>
                  </Table.Tr>
                ) : null}
              </Fragment>
            );
          })}
        </Table.Tbody>
      </Table>

      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {t("catalog.columns.pageShowing", {
            from: filtered.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1,
            to: Math.min(page * PAGE_SIZE, filtered.length),
            total: filtered.length,
          })}
        </Text>
        <Pagination
          value={page}
          onChange={setPage}
          total={Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))}
        />
      </Group>
    </Stack>
  );
}
