"use client";

import { Badge, Button, Checkbox, Group, MultiSelect, Select, Table, Text, TextInput } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { EntityListTagFilter } from "@/features/entities/EntityListTagFilter";
import { EntityRowActions } from "@/features/entities/EntityRowActions";
import { EntityStatusBadge } from "@/features/entities/EntityStatusBadge";
import { PublishStatusBadge } from "@/features/entities/PublishStatusBadge";
import { addEntityTags, listEntities, removeEntityTags } from "@/features/entities/api";
import { listTags } from "@/features/tags/api";
import {
  DEFAULT_ENTITY_LIST_STATUSES,
  createEntitySavedFilter,
  entityListRequest,
  entitySaveTarget,
  entitySavedQuery,
  loadEntitySavedFilters,
  patchEntitySavedFilter,
  rememberEntitySavedFilter,
  sameEntitySavedQuery,
  type EntitySavedFilter,
  type EntitySavedQuery,
} from "@/features/entities/entityListFilter";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { ListPresentation } from "@/lib/list-state";
import { listErrorMessage, listErrorRequestId } from "@/lib/paged-list-session";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;
const NO_TAG_IDS: readonly string[] = [];

type Gate = "reading" | "ready" | "failed";
type BulkVerb = "add" | "remove";

function ExistingTagPicker({
  label,
  emptyLabel,
  value,
  onChange,
}: {
  label: string;
  emptyLabel: string;
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [matches, setMatches] = useState<{ id: string; name: string }[]>([]);
  const [labels, setLabels] = useState<Map<string, string>>(() => new Map());

  useEffect(() => {
    const needle = search.trim();
    if (needle === "") {
      setMatches([]);
      return;
    }
    let cancelled = false;
    void listTags({ q: needle, limit: 8 })
      .then((page) => {
        if (cancelled) return;
        const found = page.items.map((item) => ({ id: item.id, name: item.name }));
        setMatches(found);
        setLabels((current) => {
          const next = new Map(current);
          for (const tag of found) next.set(tag.id, tag.name);
          return next;
        });
      })
      .catch(() => {
        if (!cancelled) setMatches([]);
      });
    return () => {
      cancelled = true;
    };
  }, [search]);

  const data = useMemo(() => {
    const byId = new Map<string, string>();
    for (const id of value) byId.set(id, labels.get(id) ?? id);
    for (const tag of matches) byId.set(tag.id, tag.name);
    return [...byId].map(([id, name]) => ({ value: id, label: name }));
  }, [labels, matches, value]);

  return (
    <MultiSelect
      aria-label={label}
      placeholder={value.length === 0 ? label : undefined}
      data={data}
      value={value}
      onChange={onChange}
      searchValue={search}
      onSearchChange={setSearch}
      searchable
      hidePickedOptions
      filter={({ options }) => options}
      nothingFoundMessage={search.trim() === "" ? undefined : emptyLabel}
    />
  );
}

export function EntityList() {
  const t = useTranslate();
  const { open } = useNotification();
  const showInstant = useShowInstant();
  const { data: canWrite } = useCan({
    resource: ModuleId.entities,
    action: ModuleAction.edit,
  });
  const canEdit = Boolean(canWrite?.can);
  const searchParams = useSearchParams();
  const arrivedWithQuery = useRef(searchParams.toString() !== "").current;
  const [gate, setGate] = useState<Gate>(arrivedWithQuery ? "ready" : "reading");
  const [attempt, setAttempt] = useState(0);
  const [gateError, setGateError] = useState<string | null>(null);
  const [gateRequestId, setGateRequestId] = useState<string | null>(null);
  const [filters, setFilters] = useState<EntitySavedFilter[]>([]);
  const [rememberedId, setRememberedId] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const pendingQuery = useRef<EntitySavedQuery | null>(null);
  const query = useListQuery({
    filters: [
      {
        key: "status",
        type: "multi",
        defaultValue: DEFAULT_ENTITY_LIST_STATUSES,
      },
      {
        key: "tag_id",
        type: "multi",
        defaultValue: NO_TAG_IDS,
      },
    ],
  });
  const queryRef = useRef(query);
  queryRef.current = query;
  const statusQuery = query.multi("status");
  const tagIds = query.multi("tag_id");
  const currentQuery = useMemo(
    () => entitySavedQuery({ q: query.search, statuses: statusQuery, tagIds }),
    [query.search, statusQuery, tagIds],
  );
  const selectionScope = `${query.page}\0${query.search}\0${statusQuery.join("\0")}\0${tagIds.join("\0")}`;
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set());
  const [selectionScopeSeen, setSelectionScopeSeen] = useState(selectionScope);
  const [bulk, setBulk] = useState<BulkVerb | null>(null);
  const [bulkTagIds, setBulkTagIds] = useState<string[]>([]);
  const [applying, setApplying] = useState(false);
  if (selectionScopeSeen !== selectionScope) {
    setSelectionScopeSeen(selectionScope);
    setChecked(new Set());
    setBulk(null);
    setBulkTagIds([]);
  }

  useEffect(() => {
    let cancelled = false;
    if (arrivedWithQuery) {
      void loadEntitySavedFilters()
        .then((loaded) => {
          if (cancelled) return;
          setFilters(loaded.filters);
          setRememberedId(loaded.rememberedId);
        })
        .catch(() => {
          // The address is already the query. Leave it, and leave the picker empty.
        });
      return () => {
        cancelled = true;
      };
    }
    setGate("reading");
    void loadEntitySavedFilters()
      .then((loaded) => {
        if (cancelled) return;
        setFilters(loaded.filters);
        setRememberedId(loaded.rememberedId);
        const remembered = loaded.filters.find(
          (item) => item.id === loaded.rememberedId,
        );
        if (!remembered) {
          pendingQuery.current = null;
          setAppliedId(null);
          setGate("ready");
          return;
        }
        const listQuery = queryRef.current;
        const before = entitySavedQuery({
          q: listQuery.search,
          statuses: listQuery.multi("status"),
          tagIds: listQuery.multi("tag_id"),
        });
        const target = entitySavedQuery({
          q: remembered.query.q,
          statuses: remembered.query.status,
          tagIds: remembered.query.tag_ids,
        });
        setAppliedId(remembered.id);
        setNameDraft(remembered.name);
        listQuery.setSearch(target.q);
        listQuery.setFilter("status", target.status);
        listQuery.setFilter("tag_id", target.tag_ids);
        listQuery.setPage(1);
        if (sameEntitySavedQuery(before, target)) {
          pendingQuery.current = null;
          setGate("ready");
          return;
        }
        pendingQuery.current = target;
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        pendingQuery.current = null;
        setGateError(listErrorMessage(error));
        setGateRequestId(listErrorRequestId(error));
        setGate("failed");
      });
    return () => {
      cancelled = true;
    };
  }, [arrivedWithQuery, attempt]);

  useEffect(() => {
    const target = pendingQuery.current;
    if (!target || gate !== "reading") return;
    if (!sameEntitySavedQuery(currentQuery, target)) return;
    pendingQuery.current = null;
    setGate("ready");
  }, [currentQuery, gate]);

  const fetchPage = useCallback(
    (pageQuery: PageQuery) => {
      const request = entityListRequest({
        q: query.search,
        statuses: statusQuery,
        tagIds,
        limit: pageQuery.limit,
        offset: pageQuery.offset,
      });
      if (request === null) {
        return {
          items: [],
          total: 0,
          limit: pageQuery.limit,
          offset: pageQuery.offset,
        };
      }
      return listEntities(request);
    },
    [query.search, statusQuery, tagIds],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, statusQuery, tagIds],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
    enabled: gate === "ready",
  });
  const { items } = list;
  const knownTags = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of items) {
      for (const tag of row.tags) names.set(tag.id, tag.name);
    }
    return names;
  }, [items]);
  const selectedIds = canEdit
    ? items.flatMap((row) => (checked.has(row.id) ? [row.id] : []))
    : [];
  const allChecked = items.length > 0 && selectedIds.length === items.length;
  const someChecked = selectedIds.length > 0;

  function openBulk(verb: BulkVerb) {
    setBulkTagIds([]);
    setBulk(verb);
  }

  async function applyBulk() {
    if (bulk === null || selectedIds.length === 0 || bulkTagIds.length === 0) return;
    const verb = bulk;
    const body = { entity_ids: selectedIds, tag_ids: bulkTagIds };
    setApplying(true);
    try {
      if (verb === "add") await addEntityTags(body);
      else await removeEntityTags(body);
      setChecked(new Set());
      setBulk(null);
      setBulkTagIds([]);
      open?.({
        type: "success",
        message: t(verb === "add" ? "entities.bulk.added" : "entities.bulk.removed"),
      });
      await list.reload();
    } catch (error) {
      report(error);
    } finally {
      setApplying(false);
    }
  }
  const matchedId =
    filters.find((item) => sameEntitySavedQuery(item.query, currentQuery))?.id ??
    null;
  const selectedId = appliedId ?? matchedId;
  const selected = filters.find((item) => item.id === selectedId) ?? null;

  useEffect(() => {
    setNameDraft(selected?.name ?? "");
    setNameError(null);
  }, [selectedId, selected?.name]);

  function report(error: unknown) {
    open?.({ type: "error", message: listErrorMessage(error) });
  }

  async function choose(id: string) {
    const filter = filters.find((item) => item.id === id);
    if (!filter) return;
    try {
      await rememberEntitySavedFilter(filter.id);
    } catch (error) {
      report(error);
      return;
    }
    const target = entitySavedQuery({
      q: filter.query.q,
      statuses: filter.query.status,
      tagIds: filter.query.tag_ids,
    });
    query.setSearch(target.q);
    query.setFilter("status", target.status);
    query.setFilter("tag_id", target.tag_ids);
    query.setPage(1);
    setRememberedId(filter.id);
    setAppliedId(filter.id);
    setNameDraft(filter.name);
  }

  async function forget() {
    try {
      await rememberEntitySavedFilter(null);
    } catch (error) {
      report(error);
      return;
    }
    query.clear();
    setRememberedId(null);
    setAppliedId(null);
    setNameDraft("");
  }

  async function save() {
    const target = entitySaveTarget({
      appliedId,
      stored: filters,
      current: currentQuery,
    });
    if (target.kind === "create" && nameDraft.trim() === "") {
      setNameError(t("savedFilters.nameRequired"));
      return;
    }
    setSaving(true);
    try {
      if (target.kind === "update") {
        const existing = filters.find((item) => item.id === target.id);
        const draft = nameDraft.trim();
        const body: { name?: string; query: EntitySavedQuery } = {
          query: currentQuery,
        };
        if (draft !== "" && existing && draft !== existing.name) body.name = draft;
        const updated = await patchEntitySavedFilter(target.id, body);
        const next = {
          id: updated.saved_filter.id,
          name: updated.saved_filter.name,
          query: updated.saved_filter.query,
        };
        setFilters((current) =>
          current.map((item) => (item.id === next.id ? next : item)),
        );
        setNameDraft(next.name);
      } else {
        const draft = nameDraft.trim();
        const created = await createEntitySavedFilter(draft, currentQuery);
        const next = {
          id: created.saved_filter.id,
          name: created.saved_filter.name,
          query: created.saved_filter.query,
        };
        await rememberEntitySavedFilter(next.id);
        setFilters((current) => [...current, next]);
        setRememberedId(next.id);
        setAppliedId(next.id);
        setNameDraft(next.name);
      }
      open?.({ type: "success", message: t("savedFilters.saved") });
    } catch (error) {
      report(error);
    } finally {
      setSaving(false);
    }
  }

  const heldPresentation: ListPresentation =
    gate === "failed"
      ? { state: "error", refreshing: false }
      : { state: "loading", refreshing: false };
  const tableList =
    gate === "ready"
      ? list
      : {
          presentation: heldPresentation,
          error: gate === "failed" ? gateError : null,
          errorRequestId: gate === "failed" ? gateRequestId : null,
          reload: () => setAttempt((value) => value + 1),
          page: 1,
          setPage: () => undefined,
          pageSize: PAGE_SIZE,
          total: 0,
        };

  return (
    <>
    <PageChrome
      title={t("entities.title")}
      description={t("entities.description")}
      actions={
        <>
          {canEdit ? (
            <Group gap="xs">
              <Button
                type="button"
                size="sm"
                variant="default"
                disabled={selectedIds.length === 0}
                onClick={() => openBulk("add")}
              >
                {t("entities.bulk.add")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="default"
                disabled={selectedIds.length === 0}
                onClick={() => openBulk("remove")}
              >
                {t("entities.bulk.remove")}
              </Button>
            </Group>
          ) : null}
          <CreateListAction
            resource={ModuleId.entities}
            href="/console/entities/new"
          >
            {t("entities.create")}
          </CreateListAction>
        </>
      }
      toolbar={
        gate === "ready" ? (
          <ListToolbar
            query={query}
            searchPlaceholder={t("entities.search")}
            filters={[
              {
                key: "status",
                label: t("entities.fields.entityStatus"),
                options: [
                  { value: "not_serving", label: t("entities.status.notServing") },
                  { value: "serving", label: t("entities.status.serving") },
                  { value: "deprecated", label: t("entities.status.deprecated") },
                ],
              },
            ]}
            extra={
              <>
                <EntityListTagFilter
                  value={tagIds}
                  onChange={(ids) => query.setFilter("tag_id", ids)}
                  known={knownTags}
                />
                <Select
                  aria-label={t("savedFilters.list")}
                  placeholder={t("savedFilters.placeholder")}
                  data={filters.map((item) => ({ value: item.id, label: item.name }))}
                  value={selectedId}
                  onChange={(id) => {
                    if (id) void choose(id);
                  }}
                  searchable
                  miw={180}
                />
                <TextInput
                  aria-label={t("savedFilters.name")}
                  placeholder={t("savedFilters.name")}
                  value={nameDraft}
                  error={nameError}
                  onChange={(event) => {
                    setNameDraft(event.currentTarget.value);
                    setNameError(null);
                  }}
                  w={160}
                />
                <Button
                  type="button"
                  size="xs"
                  loading={saving}
                  onClick={() => void save()}
                >
                  {t("savedFilters.save")}
                </Button>
                {rememberedId ? (
                  <Button type="button" size="xs" variant="subtle" onClick={() => void forget()}>
                    {t("savedFilters.clear")}
                  </Button>
                ) : null}
              </>
            }
          />
        ) : undefined
      }
    >
      <ListTable
        list={tableList}
        columnCount={canEdit ? 8 : 7}
        emptyMessage={t("entities.list.empty")}
        emptyAction={
          <CreateListAction
            resource={ModuleId.entities}
            href="/console/entities/new"
          >
            {t("entities.create")}
          </CreateListAction>
        }
        noMatchMessage={t("entities.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            {canEdit ? (
              <Table.Th w={40}>
                <Checkbox
                  aria-label={t("entities.bulk.selectPage")}
                  checked={allChecked}
                  indeterminate={someChecked && !allChecked}
                  onChange={(event) => {
                    setChecked(
                      event.currentTarget.checked
                        ? new Set(items.map((row) => row.id))
                        : new Set(),
                    );
                  }}
                />
              </Table.Th>
            ) : null}
            <Table.Th>{t("entities.fields.name")}</Table.Th>
            <Table.Th>{t("entities.fields.tags")}</Table.Th>
            <Table.Th>{t("entities.fields.version")}</Table.Th>
            <Table.Th>{t("entities.fields.entityStatus")}</Table.Th>
            <Table.Th>{t("entities.fields.versionStatus")}</Table.Th>
            <Table.Th>{t("entities.fields.updatedAt")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {items.map((row) => {
          const current = row.current_version;
          return (
            <Table.Tr key={row.id}>
              {canEdit ? (
                <Table.Td>
                  <Checkbox
                    aria-label={t("entities.bulk.select", { name: row.name })}
                    checked={checked.has(row.id)}
                    onChange={(event) => {
                      const on = event.currentTarget.checked;
                      setChecked((current) => {
                        const next = new Set(current);
                        if (on) next.add(row.id);
                        else next.delete(row.id);
                        return next;
                      });
                    }}
                  />
                </Table.Td>
              ) : null}
              <Table.Td>
                <RecordReference
                  name={row.name}
                  recordKey={row.table_name}
                  href={`/console/entities/${row.id}`}
                />
              </Table.Td>
              <Table.Td>
                {row.tags.length === 0 ? (
                  "—"
                ) : (
                  <Group gap={4} wrap="wrap">
                    {row.tags.map((tag) => (
                      <Badge key={tag.id} size="sm" variant="light" color="gray">
                        {tag.name}
                      </Badge>
                    ))}
                  </Group>
                )}
              </Table.Td>
              <Table.Td>{current ? current.version : "—"}</Table.Td>
              <Table.Td>
                <EntityStatusBadge entity={row} />
              </Table.Td>
              <Table.Td>
                {current ? (
                  <PublishStatusBadge publishStatus={current.publish_status} />
                ) : (
                  "—"
                )}
              </Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {showInstant(row.updated_at)}
                </Text>
              </Table.Td>
              <Table.Td>
                <EntityRowActions
                  entity={row}
                  canWrite={Boolean(canWrite?.can)}
                  onChanged={() => void list.reload()}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </PageChrome>
    <ConfirmActionModal
      opened={bulk !== null}
      onClose={() => {
        if (applying) return;
        setBulk(null);
        setBulkTagIds([]);
      }}
      title={t(bulk === "remove" ? "entities.bulk.removeTitle" : "entities.bulk.addTitle")}
      body={t(bulk === "remove" ? "entities.bulk.removeBody" : "entities.bulk.addBody")}
      confirmLabel={t(
        bulk === "remove" ? "entities.bulk.confirmRemove" : "entities.bulk.confirmAdd",
      )}
      confirmDisabled={bulkTagIds.length === 0 || selectedIds.length === 0}
      loading={applying}
      onConfirm={() => void applyBulk()}
    >
      <ExistingTagPicker
        label={t("entities.bulk.tags")}
        emptyLabel={t("entities.list.tagNone")}
        value={bulkTagIds}
        onChange={setBulkTagIds}
      />
    </ConfirmActionModal>
    </>
  );
}
