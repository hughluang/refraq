"use client";

import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import {
  CopyIcon,
  SearchIcon,
  StatusDotIcon,
} from "@/components/icons";
import { FillColumn } from "@/components/layout/FillColumn";
import { isEditableShortcutTarget } from "@/components/layout/consoleNav";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useLeaveGuardRegistration } from "@/components/navigation/leaveGuard";
import { patchColumnSemanticsBatch } from "@/features/sources/api/semantics";
import { ColumnInspector } from "@/features/sources/catalog-detail/ColumnInspector";
import {
  type ColumnDraft,
  type ColumnFilter,
  batchItemsFromDirty,
  dirtyColumnIds,
  distinctNormalizedTypes,
  draftFromColumn,
  draftsFromColumns,
  filterColumns,
  foreignKeyMap,
  foreignKeyNames,
  hasUnknownNormalizedType,
  indexedNames,
  primaryKeyNames,
  shouldReplaceColumnDrafts,
  uniqueKeyNames,
} from "@/features/sources/catalog-detail/columnDrafts";
import { useSemanticsSave } from "@/features/sources/catalog-detail/useSemanticsSave";
import type { CatalogObject } from "@/features/sources/types";
import { usePagedList } from "@/hooks/usePagedList";
import { copyText } from "@/lib/copy-text";
import { offsetPageFromItems, type PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type ColumnsTabProps = {
  object: CatalogObject;
  writable: boolean;
  onSaved: (object: CatalogObject) => void;
  reloadEpoch?: number;
  inspectedColumnId?: string | null;
  onInspectColumnChange?: (columnId: string | null) => void;
  externalFilterRequest?: { filter: "all" | "empty"; nonce: number } | null;
};

export function ColumnsTab({
  object,
  writable,
  onSaved,
  reloadEpoch = 0,
  inspectedColumnId,
  onInspectColumnChange,
  externalFilterRequest,
}: ColumnsTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const { saving, save } = useSemanticsSave(onSaved);
  const [savingSingleId, setSavingSingleId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ColumnDraft>>({});
  const [baseline, setBaseline] = useState<Record<string, ColumnDraft>>({});
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<ColumnFilter>("all");
  const [normalizedType, setNormalizedType] = useState("all");
  const [internalInspectedId, setInternalInspectedId] = useState<string | null>(
    null,
  );
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const draftScopeRef = useRef<{
    objectId?: string;
    reloadEpoch?: number;
  }>({});
  const lastFilterNonceRef = useRef<number | undefined>(undefined);

  const isControlledInspect = inspectedColumnId !== undefined;
  const inspectedId = isControlledInspect
    ? inspectedColumnId
    : internalInspectedId;

  const selectColumn = useCallback(
    (columnId: string | null) => {
      if (!isControlledInspect) {
        setInternalInspectedId(columnId);
      }
      onInspectColumnChange?.(columnId);
    },
    [isControlledInspect, onInspectColumnChange],
  );

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
    if (previous.objectId !== undefined && previous.objectId !== object.id) {
      selectColumn(null);
    }
  }, [object.id, object.columns, reloadEpoch, selectColumn]);

  const pkSet = useMemo(
    () => primaryKeyNames(object.primary_key),
    [object.primary_key],
  );
  const fkSet = useMemo(
    () => foreignKeyNames(object.foreign_keys),
    [object.foreign_keys],
  );
  const fkMap = useMemo(
    () => foreignKeyMap(object.foreign_keys),
    [object.foreign_keys],
  );
  const ukSet = useMemo(
    () => uniqueKeyNames(object.indexes),
    [object.indexes],
  );
  const idxSet = useMemo(
    () => indexedNames(object.indexes),
    [object.indexes],
  );
  const normalizedTypeOptions = useMemo(
    () => distinctNormalizedTypes(object.columns),
    [object.columns],
  );
  const hasUnknownType = useMemo(
    () => hasUnknownNormalizedType(object.columns),
    [object.columns],
  );

  const dirtyIds = useMemo(
    () => dirtyColumnIds(object.columns, drafts, baseline),
    [object.columns, drafts, baseline],
  );
  const dirtyIdSet = useMemo(() => new Set(dirtyIds), [dirtyIds]);

  useLeaveGuardRegistration(writable && dirtyIds.length > 0);

  const filtered = useMemo(
    () =>
      filterColumns(object.columns, drafts, {
        query: q,
        filter,
        normalizedType,
        pkNames: pkSet,
        fkNames: fkSet,
        indexedNames: idxSet,
        dirtyIds: dirtyIdSet,
        baseline,
      }),
    [
      object.columns,
      drafts,
      baseline,
      q,
      filter,
      normalizedType,
      pkSet,
      fkSet,
      idxSet,
      dirtyIdSet,
    ],
  );

  const isFiltered =
    q.trim() !== "" || filter !== "all" || normalizedType !== "all";
  const filteredIds = filtered.map((col) => col.id).join(",");
  const filteredRef = useRef(filtered);
  filteredRef.current = filtered;

  const fetchPage = useCallback(
    (query: PageQuery) => offsetPageFromItems(filteredRef.current, query),
    [],
  );
  const translateRef = useRef(t);
  translateRef.current = t;
  const reloadRef = useRef<() => Promise<void>>(async () => {});
  const onError = useCallback((error: unknown) => {
    presentProblemNotification(translateRef.current, error, {
      onRetry: () => {
        void reloadRef.current();
      },
    });
  }, []);

  const list = usePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [q, filter, normalizedType, object.id, reloadEpoch, filteredIds],
    filtered: isFiltered,
    initialLoading: false,
    onError,
  });
  reloadRef.current = list.reload;

  useEffect(() => {
    if (!externalFilterRequest) return;
    if (lastFilterNonceRef.current === externalFilterRequest.nonce) {
      return;
    }
    lastFilterNonceRef.current = externalFilterRequest.nonce;
    setFilter(externalFilterRequest.filter);
    list.setPage(1);
  }, [externalFilterRequest, list.setPage]);

  const inspectedIndex = useMemo(
    () =>
      inspectedId
        ? filtered.findIndex((col) => col.id === inspectedId)
        : -1,
    [filtered, inspectedId],
  );
  const inspectedColumn =
    inspectedId != null
      ? (object.columns.find((col) => col.id === inspectedId) ?? null)
      : null;

  const goPrevColumn = useCallback(() => {
    if (inspectedIndex <= 0) return;
    const prev = filtered[inspectedIndex - 1];
    if (prev) selectColumn(prev.id);
  }, [filtered, inspectedIndex, selectColumn]);

  const goNextColumn = useCallback(() => {
    if (inspectedIndex < 0 || inspectedIndex >= filtered.length - 1) return;
    const next = filtered[inspectedIndex + 1];
    if (next) selectColumn(next.id);
  }, [filtered, inspectedIndex, selectColumn]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing) return;
      if (
        event.key === "/" &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        if (isEditableShortcutTarget(event.target)) return;
        event.preventDefault();
        searchInputRef.current?.focus();
        return;
      }
      if (inspectedColumn && event.altKey && event.key === "ArrowUp") {
        event.preventDefault();
        goPrevColumn();
        return;
      }
      if (inspectedColumn && event.altKey && event.key === "ArrowDown") {
        event.preventDefault();
        goNextColumn();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [inspectedColumn, goPrevColumn, goNextColumn]);

  const updateDraft = useCallback(
    (columnId: string, patch: Partial<ColumnDraft>) => {
      setDrafts((prev) => {
        const col = object.columns.find((c) => c.id === columnId);
        const current = prev[columnId] ?? (col ? draftFromColumn(col) : undefined);
        if (!current) return prev;
        return {
          ...prev,
          [columnId]: {
            ...current,
            ...patch,
          },
        };
      });
    },
    [object.columns],
  );

  const resetColumn = useCallback(
    (columnId: string) => {
      setDrafts((prev) => {
        const base = baseline[columnId];
        if (!base) return prev;
        return { ...prev, [columnId]: base };
      });
    },
    [baseline],
  );

  const discardAllChanges = useCallback(() => {
    setDrafts(baseline);
    setDiscardConfirmOpen(false);
  }, [baseline]);

  const handleDiscardClick = () => {
    if (dirtyIds.length > 1) {
      setDiscardConfirmOpen(true);
      return;
    }
    discardAllChanges();
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

  const saveSingle = async (columnId: string) => {
    if (!dirtyIdSet.has(columnId)) return;
    setSavingSingleId(columnId);
    try {
      const saved = await save(() =>
        patchColumnSemanticsBatch(
          object.id,
          batchItemsFromDirty(object.columns, drafts, [columnId]),
        ),
      );
      if (!saved) return;
      const savedCol = saved.columns.find((c) => c.id === columnId);
      if (!savedCol) return;
      const nextColDraft = draftFromColumn(savedCol);
      setBaseline((prev) => ({ ...prev, [columnId]: nextColDraft }));
      setDrafts((prev) => ({ ...prev, [columnId]: nextColDraft }));
    } finally {
      setSavingSingleId(null);
    }
  };

  const clearFilters = useCallback(() => {
    setQ("");
    setFilter("all");
    setNormalizedType("all");
  }, []);

  const copyLocator = async (locator: string) => {
    try {
      await copyText(locator);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  };

  const inspectedDraft = inspectedColumn
    ? (drafts[inspectedColumn.id] ?? draftFromColumn(inspectedColumn))
    : null;

  return (
    <FillColumn gap="sm">
      <Stack gap="xs" style={{ flexShrink: 0 }}>
        <Group align="flex-end" wrap="wrap" gap="sm">
          <TextInput
            ref={searchInputRef}
            aria-label={t("catalog.columns.search")}
            placeholder={t("catalog.columns.searchPlaceholder")}
            leftSection={<SearchIcon size={14} />}
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
            w={300}
          />
          <Select
            aria-label={t("catalog.columns.filter")}
            placeholder={t("catalog.columns.filter")}
            value={filter}
            onChange={(v) => setFilter((v as ColumnFilter) || "all")}
            data={[
              { value: "all", label: t("catalog.columns.filterAll") },
              { value: "empty", label: t("catalog.columns.filterEmpty") },
              { value: "filled", label: t("catalog.columns.filterFilled") },
              { value: "dirty", label: t("catalog.columns.filterDirty") },
              { value: "enum", label: t("catalog.columns.filterEnum") },
              { value: "pk", label: t("catalog.columns.filterPk") },
              { value: "fk", label: t("catalog.columns.filterFk") },
              { value: "indexed", label: t("catalog.columns.filterIndexed") },
              { value: "absent", label: t("catalog.columns.filterAbsent") },
            ]}
            w={180}
          />
          <Select
            aria-label={t("catalog.columns.normalizedTypeFilter")}
            placeholder={t("catalog.columns.normalizedTypeFilter")}
            value={normalizedType}
            onChange={(v) => setNormalizedType(v || "all")}
            data={[
              {
                value: "all",
                label: t("catalog.columns.normalizedTypeAll"),
              },
              ...normalizedTypeOptions.map((nt) => ({
                value: nt,
                label: nt,
              })),
            ]}
            w={180}
          />
          {hasUnknownType ? (
            <ConsoleLink href="/console/type-mappings">
              <Text size="xs">{t("catalog.columns.typeMappingsLink")}</Text>
            </ConsoleLink>
          ) : null}
          {isFiltered ? (
            <Button size="xs" variant="subtle" onClick={clearFilters}>
              {t("catalog.columns.clearFilters")}
            </Button>
          ) : null}
        </Group>

        {writable && dirtyIds.length > 0 ? (
          <Group
            gap="sm"
            px="sm"
            py={6}
            style={{
              border: "1px solid var(--refraq-tone-warning-border)",
              borderRadius: "var(--mantine-radius-sm)",
            }}
          >
            <Badge size="sm" color="yellow" variant="light">
              {t("catalog.columns.dirtyHint", { count: dirtyIds.length })}
            </Badge>
            <Button
              size="xs"
              loading={saving && !savingSingleId}
              onClick={() => void saveDirty()}
            >
              {t("catalog.columns.saveDirty", { count: dirtyIds.length })}
            </Button>
            <Button
              size="xs"
              variant="subtle"
              color="red"
              onClick={handleDiscardClick}
            >
              {t("catalog.columns.discardChanges")}
            </Button>
          </Group>
        ) : null}
      </Stack>

      <Group
        align="stretch"
        gap="md"
        wrap="nowrap"
        flex={1}
        mih={0}
        style={{ minHeight: 0 }}
      >
        <Box
          flex={1}
          mih={0}
          style={{
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <ListTable
            list={list}
            columnCount={5}
            minWidth={760}
            emptyMessage={t("catalog.columns.empty")}
            noMatchMessage={t("catalog.columns.noMatch")}
            onClearFilters={isFiltered ? clearFilters : undefined}
            head={
              <Table.Tr>
                <Table.Th w={56}>#</Table.Th>
                <Table.Th>{t("catalog.fields.column")}</Table.Th>
                <Table.Th>{t("catalog.fields.dataType")}</Table.Th>
                <Table.Th>{t("catalog.columns.semanticsHeader")}</Table.Th>
                <Table.Th w={220}>{t("catalog.columns.signalsHeader")}</Table.Th>
              </Table.Tr>
            }
          >
            {list.items.map((col) => {
              const draft = drafts[col.id] ?? draftFromColumn(col);
              const isDirty = dirtyIdSet.has(col.id);
              const isInspected = inspectedId === col.id;
              const isPk = pkSet.has(col.name);
              const isFk = fkMap.has(col.name);
              const isUk = ukSet.has(col.name);
              const isIdx = idxSet.has(col.name);
              const semanticType = draft.column_semantics.semantic_type?.trim();
              const unit = draft.column_semantics.unit?.trim();
              const valuePattern = draft.column_semantics.value_pattern?.trim();
              const enumCount = draft.enum_catalog.length;

              return (
                <Table.Tr key={col.id}>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Text size="xs" c="dimmed">
                        {col.ordinal}
                      </Text>
                      {isDirty ? (
                        <StatusDotIcon
                          size={8}
                          color="var(--mantine-color-yellow-6)"
                        />
                      ) : null}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap={3}>
                      <Group gap={4} wrap="wrap">
                        <Text
                          size="sm"
                          ff="monospace"
                          fw={isDirty ? 600 : 500}
                        >
                          {col.name}
                        </Text>
                        <Tooltip label={col.locator_key}>
                          <ActionIcon
                            variant="subtle"
                            size="xs"
                            aria-label={t("catalog.detail.locator")}
                            onClick={() => void copyLocator(col.locator_key)}
                          >
                            <CopyIcon size={12} />
                          </ActionIcon>
                        </Tooltip>
                        {isPk ? (
                          <Badge size="xs">{t("catalog.columns.badgePk")}</Badge>
                        ) : null}
                        {isFk ? (
                          <Badge size="xs" color="grape">
                            {t("catalog.columns.badgeFk")}
                          </Badge>
                        ) : null}
                        {isUk ? (
                          <Badge size="xs" color="indigo" variant="light">
                            {t("catalog.columns.badgeUk")}
                          </Badge>
                        ) : null}
                        {isIdx ? (
                          <Badge size="xs" color="cyan" variant="light">
                            {t("catalog.columns.badgeIdx")}
                          </Badge>
                        ) : null}
                        {!col.nullable ? (
                          <Badge size="xs" variant="outline" color="gray">
                            {t("catalog.columns.badgeNotNull")}
                          </Badge>
                        ) : null}
                        {!col.is_present ? (
                          <Badge size="xs" color="gray">
                            {t("catalog.fields.absentValue")}
                          </Badge>
                        ) : null}
                      </Group>
                      {col.comment ? (
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {col.comment}
                        </Text>
                      ) : null}
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap={3}>
                      <Group gap={6} wrap="wrap">
                        <Text size="xs" ff="monospace">
                          {col.data_type}
                        </Text>
                        {col.normalized_type === "unknown" ? (
                          <Badge size="xs" color="orange" variant="filled">
                            {t("catalog.fields.normalizedTypeUnknown")}
                          </Badge>
                        ) : col.normalized_type ? (
                          <Badge size="xs" variant="light" color="gray">
                            {col.normalized_type}
                          </Badge>
                        ) : null}
                      </Group>
                      {col.default_value ? (
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {t("catalog.structure.default")}: {col.default_value}
                        </Text>
                      ) : null}
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    {writable ? (
                      <Stack gap={4}>
                        <TextInput
                          size="xs"
                          aria-label={`${col.name} ${t("catalog.semantics.businessName")}`}
                          placeholder={t("catalog.semantics.businessName")}
                          value={draft.business_name}
                          onChange={(e) =>
                            updateDraft(col.id, {
                              business_name: e.currentTarget.value,
                            })
                          }
                        />
                        <TextInput
                          size="xs"
                          aria-label={`${col.name} ${t("catalog.semantics.businessDescription")}`}
                          placeholder={t(
                            "catalog.semantics.businessDescription",
                          )}
                          value={draft.business_description}
                          onChange={(e) =>
                            updateDraft(col.id, {
                              business_description: e.currentTarget.value,
                            })
                          }
                        />
                      </Stack>
                    ) : (
                      <Stack gap={2}>
                        <Text size="sm" fw={draft.business_name ? 500 : 400}>
                          {draft.business_name || "—"}
                        </Text>
                        {draft.business_description ? (
                          <Text size="xs" c="dimmed" lineClamp={2}>
                            {draft.business_description}
                          </Text>
                        ) : null}
                      </Stack>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group justify="space-between" align="center" wrap="nowrap">
                      <Group gap={4} wrap="wrap">
                        {semanticType ? (
                          <Badge size="xs" variant="light">
                            {semanticType}
                          </Badge>
                        ) : null}
                        {unit ? (
                          <Badge size="xs" variant="outline" color="teal">
                            {unit}
                          </Badge>
                        ) : null}
                        {valuePattern ? (
                          <Badge size="xs" variant="outline" color="gray">
                            {valuePattern}
                          </Badge>
                        ) : null}
                        {enumCount > 0 ? (
                          <Badge size="xs" variant="light" color="grape">
                            enum ({enumCount})
                          </Badge>
                        ) : null}
                      </Group>
                      <Button
                        size="compact-xs"
                        variant={isInspected ? "filled" : "light"}
                        aria-expanded={isInspected}
                        onClick={() =>
                          selectColumn(isInspected ? null : col.id)
                        }
                      >
                        {t("catalog.columns.inspect")}
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </ListTable>
        </Box>

        {inspectedColumn && inspectedDraft ? (
          <ColumnInspector
            column={inspectedColumn}
            draft={inspectedDraft}
            writable={writable}
            isDirty={dirtyIdSet.has(inspectedColumn.id)}
            savingSingle={saving && savingSingleId === inspectedColumn.id}
            foreignKeys={fkMap.get(inspectedColumn.name) ?? []}
            hasPrev={inspectedIndex > 0}
            hasNext={
              inspectedIndex >= 0 && inspectedIndex < filtered.length - 1
            }
            onPrev={goPrevColumn}
            onNext={goNextColumn}
            onClose={() => selectColumn(null)}
            onChangeDraft={(patch) => updateDraft(inspectedColumn.id, patch)}
            onSaveSingle={() => void saveSingle(inspectedColumn.id)}
            onReset={() => resetColumn(inspectedColumn.id)}
          />
        ) : null}
      </Group>

      <ConfirmActionModal
        opened={discardConfirmOpen}
        onClose={() => setDiscardConfirmOpen(false)}
        title={t("catalog.columns.discardConfirmTitle")}
        body={t("catalog.columns.discardConfirmBody", {
          count: dirtyIds.length,
        })}
        confirmLabel={t("catalog.columns.discardChanges")}
        confirmColor="red"
        onConfirm={discardAllChanges}
      />
    </FillColumn>
  );
}
