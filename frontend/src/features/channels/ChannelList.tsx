"use client";

import { Badge, Button, Checkbox, Group, MultiSelect, Select, Table, TextInput } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive } from "@/components/display/statusTone";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { addChannelTags, listChannels, removeChannelTags } from "@/features/channels/api";
import { ChannelListTagFilter } from "@/features/channels/ChannelListTagFilter";
import {
  channelListRequest,
  channelSaveTarget,
  channelSavedQuery,
  createChannelSavedFilter,
  loadChannelSavedFilters,
  patchChannelSavedFilter,
  rememberChannelSavedFilter,
  sameChannelSavedQuery,
  type ChannelSavedFilter,
  type ChannelSavedQuery,
} from "@/features/channels/channelListFilter";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { listTags } from "@/features/tags/api";
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

function activeValue(active: boolean | null): string {
  if (active === true) return "true";
  if (active === false) return "false";
  return "";
}

export function ChannelList() {
  const t = useTranslate();
  const { open } = useNotification();
  const showInstant = useShowInstant();
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const canEdit = Boolean(canWrite?.can);
  const query = useListQuery({
    filters: [
      { key: "active", type: "select", defaultValue: "" },
      { key: "tag_id", type: "multi", defaultValue: NO_TAG_IDS },
    ],
  });
  const arrivedWithQuery = useRef(query.initialSearch !== "").current;
  const [gate, setGate] = useState<Gate>(arrivedWithQuery ? "ready" : "reading");
  const [attempt, setAttempt] = useState(0);
  const [gateError, setGateError] = useState<string | null>(null);
  const [gateRequestId, setGateRequestId] = useState<string | null>(null);
  const [filters, setFilters] = useState<ChannelSavedFilter[]>([]);
  const [rememberedId, setRememberedId] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const pendingQuery = useRef<ChannelSavedQuery | null>(null);
  const queryRef = useRef(query);
  queryRef.current = query;
  const active = query.select("active");
  const tagIds = query.multi("tag_id");
  const currentQuery = useMemo(
    () => channelSavedQuery({ q: query.search, active, tagIds }),
    [active, query.search, tagIds],
  );
  const selectionScope = `${query.page}\0${query.search}\0${active}\0${tagIds.join("\0")}`;
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
      void loadChannelSavedFilters()
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
    void loadChannelSavedFilters()
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
        const before = channelSavedQuery({
          q: listQuery.search,
          active: listQuery.select("active"),
          tagIds: listQuery.multi("tag_id"),
        });
        const target = channelSavedQuery({
          q: remembered.query.q,
          active: activeValue(remembered.query.active),
          tagIds: remembered.query.tag_ids,
        });
        setAppliedId(remembered.id);
        setNameDraft(remembered.name);
        listQuery.setSearch(target.q);
        listQuery.setFilter("active", activeValue(target.active));
        listQuery.setFilter("tag_id", target.tag_ids);
        listQuery.setPage(1);
        if (sameChannelSavedQuery(before, target)) {
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
    if (!sameChannelSavedQuery(currentQuery, target)) return;
    pendingQuery.current = null;
    setGate("ready");
  }, [currentQuery, gate]);

  const fetchPage = useCallback(
    (page: PageQuery) =>
      listChannels(
        channelListRequest({
          q: query.search,
          active,
          tagIds,
          limit: page.limit,
          offset: page.offset,
        }),
      ),
    [active, query.search, tagIds],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, active, tagIds],
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
    const body = { channel_ids: selectedIds, tag_ids: bulkTagIds };
    setApplying(true);
    try {
      if (verb === "add") await addChannelTags(body);
      else await removeChannelTags(body);
      setChecked(new Set());
      setBulk(null);
      setBulkTagIds([]);
      open?.({
        type: "success",
        message: t(verb === "add" ? "channels.bulk.added" : "channels.bulk.removed"),
      });
      await list.reload();
    } catch (error) {
      report(error);
    } finally {
      setApplying(false);
    }
  }
  const matchedId =
    filters.find((item) => sameChannelSavedQuery(item.query, currentQuery))?.id ??
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
      await rememberChannelSavedFilter(filter.id);
    } catch (error) {
      report(error);
      return;
    }
    const target = channelSavedQuery({
      q: filter.query.q,
      active: activeValue(filter.query.active),
      tagIds: filter.query.tag_ids,
    });
    query.setSearch(target.q);
    query.setFilter("active", activeValue(target.active));
    query.setFilter("tag_id", target.tag_ids);
    query.setPage(1);
    setRememberedId(filter.id);
    setAppliedId(filter.id);
    setNameDraft(filter.name);
  }

  async function forget() {
    try {
      await rememberChannelSavedFilter(null);
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
    const target = channelSaveTarget({
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
        const body: { name?: string; query: ChannelSavedQuery } = {
          query: currentQuery,
        };
        if (draft !== "" && existing && draft !== existing.name) body.name = draft;
        const updated = await patchChannelSavedFilter(target.id, body);
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
        const created = await createChannelSavedFilter(draft, currentQuery);
        const next = {
          id: created.saved_filter.id,
          name: created.saved_filter.name,
          query: created.saved_filter.query,
        };
        await rememberChannelSavedFilter(next.id);
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

  const createAction = (
    <CreateListAction resource={ModuleId.channels} href="/console/channels/new">
      {t("channels.create")}
    </CreateListAction>
  );

  return (
    <>
    <PageChrome
      title={t("channels.title")}
      description={t("channels.description")}
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
                {t("channels.bulk.add")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="default"
                disabled={selectedIds.length === 0}
                onClick={() => openBulk("remove")}
              >
                {t("channels.bulk.remove")}
              </Button>
            </Group>
          ) : null}
          {createAction}
        </>
      }
      toolbar={
        gate === "ready" ? (
          <ListToolbar
            query={query}
            searchPlaceholder={t("channels.search")}
            filters={[
              {
                key: "active",
                label: t("channels.list.activation"),
                options: [
                  { value: "true", label: t("channels.status.active") },
                  { value: "false", label: t("channels.status.inactive") },
                ],
              },
            ]}
            extra={
              <>
                <ChannelListTagFilter
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
        columnCount={canEdit ? 6 : 5}
        emptyMessage={t("channels.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("channels.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            {canEdit ? (
              <Table.Th w={40}>
                <Checkbox
                  aria-label={t("channels.bulk.selectPage")}
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
            <Table.Th>{t("channels.fields.name")}</Table.Th>
            <Table.Th>{t("channels.fields.tags")}</Table.Th>
            <Table.Th>{t("channels.fields.active")}</Table.Th>
            <Table.Th>{t("channels.fields.latestVersion")}</Table.Th>
            <Table.Th>{t("channels.fields.updatedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {items.map((channel) => (
          <Table.Tr key={channel.id}>
            {canEdit ? (
              <Table.Td>
                <Checkbox
                  aria-label={t("channels.bulk.select", { name: channel.name })}
                  checked={checked.has(channel.id)}
                  onChange={(event) => {
                    const on = event.currentTarget.checked;
                    setChecked((current) => {
                      const next = new Set(current);
                      if (on) next.add(channel.id);
                      else next.delete(channel.id);
                      return next;
                    });
                  }}
                />
              </Table.Td>
            ) : null}
            <Table.Td>
              <RecordReference
                name={channel.name}
                recordKey={channel.id}
                href={`/console/channels/${channel.id}`}
              />
            </Table.Td>
            <Table.Td>
              {channel.tags.length === 0 ? (
                "—"
              ) : (
                <Group gap={4} wrap="wrap">
                  {channel.tags.map((tag) => (
                    <Badge key={tag.id} size="sm" variant="light" color="gray">
                      {tag.name}
                    </Badge>
                  ))}
                </Group>
              )}
            </Table.Td>
            <Table.Td>
              <Group gap={6} wrap="nowrap">
                <StatusBadge
                  tone={presentChannelActive(channel.active).tone}
                  labelKey={presentChannelActive(channel.active).labelKey}
                />
                {channel.persistently_failing ? (
                  <StatusBadge tone="warning" labelKey="channels.persistentlyFailing" />
                ) : null}
              </Group>
            </Table.Td>
            <Table.Td>
              {channel.latest_version ? channel.latest_version.number : "—"}
            </Table.Td>
            <Table.Td>{showInstant(channel.updated_at)}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
    <ConfirmActionModal
      opened={bulk !== null}
      onClose={() => {
        if (applying) return;
        setBulk(null);
        setBulkTagIds([]);
      }}
      title={t(bulk === "remove" ? "channels.bulk.removeTitle" : "channels.bulk.addTitle")}
      body={t(bulk === "remove" ? "channels.bulk.removeBody" : "channels.bulk.addBody")}
      confirmLabel={t(
        bulk === "remove" ? "channels.bulk.confirmRemove" : "channels.bulk.confirmAdd",
      )}
      confirmDisabled={bulkTagIds.length === 0 || selectedIds.length === 0}
      loading={applying}
      onConfirm={() => void applyBulk()}
    >
      <ExistingTagPicker
        label={t("channels.bulk.tags")}
        emptyLabel={t("channels.list.tagNone")}
        value={bulkTagIds}
        onChange={setBulkTagIds}
      />
    </ConfirmActionModal>
    </>
  );
}
