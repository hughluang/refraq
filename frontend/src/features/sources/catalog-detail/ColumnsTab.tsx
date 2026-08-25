"use client";

import {
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useRef, useState, useCallback, Fragment } from "react";

import { ListTable } from "@/components/display/ListTable";
import { FillColumn } from "@/components/layout/FillColumn";
import { patchColumnSemanticsBatch } from "@/features/sources/api/semantics";
import {
  type ColumnDraft,
  type ColumnFilter,
  batchItemsFromDirty,
  dirtyColumnIds,
  draftFromColumn,
  draftsFromColumns,
  filterColumns,
  foreignKeyNames,
  primaryKeyNames,
  shouldReplaceColumnDrafts,
} from "@/features/sources/catalog-detail/columnDrafts";
import { useSemanticsSave } from "@/features/sources/catalog-detail/useSemanticsSave";
import type { CatalogObject } from "@/features/sources/types";
import { usePagedList } from "@/hooks/usePagedList";
import { offsetPageFromItems, type PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type ColumnsTabProps = {
  object: CatalogObject;
  writable: boolean;
  onSaved: (object: CatalogObject) => void;
  reloadEpoch: number;
};

export function ColumnsTab({
  object,
  writable,
  onSaved,
  reloadEpoch,
}: ColumnsTabProps) {
  const t = useTranslate();
  const { saving, save } = useSemanticsSave(onSaved);
  const [drafts, setDrafts] = useState<Record<string, ColumnDraft>>({});
  const [baseline, setBaseline] = useState<Record<string, ColumnDraft>>({});
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<ColumnFilter>("all");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const draftScopeRef = useRef<{
    objectId?: string;
    reloadEpoch?: number;
  }>({});

  useEffect(() => {
    const previous = draftScopeRef.current;
    const replace = shouldReplaceColumnDrafts({
      objectId: object.id,
      previousObjectId: previous.objectId,
      reloadEpoch,
      previousReloadEpoch: previous.reloadEpoch,
    });
    draftScopeRef.current = { objectId: object.id, reloadEpoch };
    if (!replace) return;
    const next = draftsFromColumns(object.columns);
    setDrafts(next);
    setBaseline(next);
    setExpanded({});
  }, [object.id, object.columns, reloadEpoch]);

  const pkSet = useMemo(
    () => primaryKeyNames(object.primary_key),
    [object.primary_key],
  );
  const fkSet = useMemo(
    () => foreignKeyNames(object.foreign_keys),
    [object.foreign_keys],
  );

  const dirtyIds = useMemo(
    () => dirtyColumnIds(object.columns, drafts, baseline),
    [object.columns, drafts, baseline],
  );

  // Filter against saved baseline so in-progress draft edits do not reshuffle rows.
  const filtered = useMemo(
    () =>
      filterColumns(object.columns, baseline, {
        query: q,
        filter,
        pkNames: pkSet,
        fkNames: fkSet,
      }),
    [object.columns, baseline, q, filter, pkSet, fkSet],
  );
  const isFiltered = q.trim() !== "" || filter !== "all";
  const filteredIds = filtered.map((col) => col.id).join(",");
  const filteredRef = useRef(filtered);
  filteredRef.current = filtered;
  const fetchPage = useCallback(
    (query: PageQuery) => offsetPageFromItems(filteredRef.current, query),
    [],
  );
  const list = usePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [q, filter, object.id, reloadEpoch, filteredIds],
    filtered: isFiltered,
    initialLoading: false,
  });

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
    const saved = await save(() =>
      patchColumnSemanticsBatch(
        object.id,
        batchItemsFromDirty(object.columns, drafts, dirtyIds),
      ),
    );
    if (!saved) return;
    const next = draftsFromColumns(saved.columns);
    setDrafts(next);
    setBaseline(next);
  };

  return (
    <FillColumn gap="sm">
      <Group align="flex-end" wrap="wrap" style={{ flexShrink: 0 }}>
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

      <ListTable
        list={list}
        columnCount={7}
        emptyMessage={t("catalog.columns.empty")}
        noMatchMessage={t("catalog.columns.noMatch")}
        head={
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>{t("catalog.fields.column")}</Table.Th>
            <Table.Th>{t("catalog.fields.dataType")}</Table.Th>
            <Table.Th>{t("catalog.fields.nullable")}</Table.Th>
            <Table.Th>{t("catalog.semantics.businessName")}</Table.Th>
            <Table.Th>{t("catalog.semantics.businessDescription")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {list.items.map((col) => {
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
                  <Table.Td>
                    <Text size="sm">{col.data_type}</Text>
                    {col.normalized_type === "unknown" ? (
                      <Badge size="xs" color="orange" variant="filled">
                        {t("catalog.fields.normalizedTypeUnknown")}
                      </Badge>
                    ) : col.normalized_type ? (
                      <Text size="xs" c="dimmed">
                        {t("catalog.fields.normalizedType")}:{" "}
                        {col.normalized_type}
                      </Text>
                    ) : null}
                  </Table.Td>
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
      </ListTable>
    </FillColumn>
  );
}
