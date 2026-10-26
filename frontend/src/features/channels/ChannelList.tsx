"use client";

import { Badge, Button, Group, Select, Table, TextInput } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive } from "@/components/display/statusTone";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { PageChrome } from "@/components/layout/PageChrome";
import { listChannels } from "@/features/channels/api";
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
import { ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { ListPresentation } from "@/lib/list-state";
import { listErrorMessage, listErrorRequestId } from "@/lib/paged-list-session";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;
const NO_TAG_IDS: readonly string[] = [];

type Gate = "reading" | "ready" | "failed";

function activeValue(active: boolean | null): string {
  if (active === true) return "true";
  if (active === false) return "false";
  return "";
}

export function ChannelList() {
  const t = useTranslate();
  const { open } = useNotification();
  const showInstant = useShowInstant();
  const searchParams = useSearchParams();
  const arrivedWithQuery = useRef(searchParams.toString() !== "").current;
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
  const query = useListQuery({
    filters: [
      { key: "active", type: "select", defaultValue: "" },
      { key: "tag_id", type: "multi", defaultValue: NO_TAG_IDS },
    ],
  });
  const queryRef = useRef(query);
  queryRef.current = query;
  const active = query.select("active");
  const tagIds = query.multi("tag_id");
  const currentQuery = useMemo(
    () => channelSavedQuery({ q: query.search, active, tagIds }),
    [active, query.search, tagIds],
  );

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
    <PageChrome
      title={t("channels.title")}
      description={t("channels.description")}
      actions={createAction}
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
        columnCount={5}
        emptyMessage={t("channels.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("channels.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
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
  );
}
