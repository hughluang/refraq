"use client";

import { Anchor, Button, Drawer, SimpleGrid, Stack, Table, Text, TextInput, Title, UnstyledButton } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useDebouncedCallback } from "@mantine/hooks";
import { useConsoleLocation } from "@/components/navigation/useConsoleNavigation";
import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { ListTable } from "@/components/display/ListTable";
import { StatusBadge } from "@/components/display/StatusBadge";
import { Callout } from "@/components/feedback/Callout";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { RecordPicker } from "@/components/form/RecordPicker";
import { catalogSourceAdapter } from "@/components/form/recordPickerAdapters";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listMirrorTables, setCatalogMirrorEnabled, type MirrorTable } from "@/features/sources/api/catalog";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { SEARCH_DEBOUNCE_MS } from "@/hooks/useSearchDebounce";
import type { PageQuery } from "@/lib/pagination";
import { presentConsoleNotification } from "@/providers/notification-provider";
import { MirrorCopySummary, MirrorWaitDependency, MirrorStatusFreshness } from "./MirrorCopySummary";
import { MirrorSwitch } from "./MirrorSwitch";
import { mirrorDetailHref, rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";
import { useMirrorStatus } from "./useMirrorStatus";

const tableFilters = [{ key: "tableSource", type: "select", defaultValue: "" }] as const;
const tablePageSize = 10;

type DrawerProps = { objectId?: string; sourceId?: string; disabled?: boolean; onAccepted?: () => void };

export function MirrorTableDrawer({ objectId, sourceId, disabled, onAccepted }: DrawerProps) {
  const t = useTranslate();
  const { data: read } = useCan({ resource: "mirrors", action: "show" });
  const { data: write } = useCan({ resource: "mirrors", action: "edit" });
  const canRead = !!read?.can;
  const canWrite = !!write?.can;
  const { search } = useConsoleLocation();
  const external = search.get("mirrorTable");
  const [view, setView] = useState(external);
  useEffect(() => setView(external), [external]);
  const picker = !objectId;
  const opened = view !== null && (picker || view === objectId);
  const query = useListQuery({ search: "tableQuery", pageKey: "tablePage", filters: tableFilters });

  function navigate(next: string | null) {
    const url = new URL(window.location.href);
    if (next === null) {
      for (const key of ["mirrorTable", "tableSource", "tableQuery", "tablePage"]) url.searchParams.delete(key);
    } else {
      url.searchParams.set("mirrorTable", next);
      if (!opened && picker && sourceId) url.searchParams.set("tableSource", sourceId);
    }
    window.history.pushState(null, "", url.pathname + url.search);
    setView(next);
  }

  return <>
    <Button variant="light" size="sm" disabled={disabled} onClick={() => navigate(objectId ?? "list")}>
      {t(picker ? "mirrors.chooseTable" : "mirrors.synchronization")}
    </Button>
    <Drawer position="right" size="lg" opened={opened} onClose={() => navigate(null)}
      title={t(view === "list" ? "mirrors.chooseTable" : "mirrors.synchronization")}
      closeButtonProps={{ "aria-label": t("mirrors.closeDrawer") }}>
      {opened && (view === "list"
        ? <MirrorTablePicker key={`${canRead}-${canWrite}`} query={query} onSelect={navigate} showSetting={canRead || canWrite} />
        : <Stack>
            {picker && <Button variant="subtle" w="fit-content" onClick={() => navigate("list")}>{t("mirrors.backToTables")}</Button>}
            <TableSetting key={`${view}-${canRead}-${canWrite}`} objectId={view!} canRead={canRead} canWrite={canWrite} onAccepted={onAccepted} />
          </Stack>)}
    </Drawer>
  </>;
}

function MirrorTablePicker({ query, onSelect, showSetting }: {
  query: ReturnType<typeof useListQuery>; onSelect: (id: string) => void; showSetting: boolean;
}) {
  const t = useTranslate();
  const { href, search: addressQuery } = useConsoleLocation();
  const source = query.select("tableSource");
  const [draft, setDraft] = useState(query.search);
  const search = query.search;
  const submitSearch = useDebouncedCallback(query.setSearch, SEARCH_DEBOUNCE_MS);
  const externalSearch = addressQuery.get("tableQuery") ?? "";
  useEffect(() => {
    submitSearch.cancel();
    setDraft(externalSearch);
  }, [href, externalSearch, submitSearch]);
  const fetch = useCallback((page: PageQuery) => listMirrorTables({ ...page, source_id: source, q: search }), [source, search]);
  const list = useConsolePagedList({ fetch, pageSize: tablePageSize, page: query.page, onPageChange: query.setPage, filtered: query.isFiltered });
  useEffect(() => {
    if (!list.loading) restoreMirrorPosition(href);
  }, [href, list.loading]);
  return <Stack>
    <RecordPicker editable clearable label={t("mirrors.source")} placeholder={t("mirrors.allSources")}
      adapter={catalogSourceAdapter} value={source} onChange={id => query.setFilter("tableSource", id ?? "")} />
    <TextInput label={t("mirrors.tableSearch")} value={draft} onChange={event => {
      setDraft(event.currentTarget.value);
      submitSearch(event.currentTarget.value);
    }} onKeyDown={event => {
      if (event.key === "Enter") submitSearch.flush();
    }} />
    <ListTable embedded list={list} columnCount={showSetting ? 3 : 2} minWidth={0}
      emptyMessage={t("mirrors.noCatalogTables")} noMatchMessage={t("catalog.list.noMatch")}
      onClearFilters={() => { submitSearch.cancel(); setDraft(""); query.clear(); }}
      head={<Table.Tr>
        <Table.Th>{t("mirrors.tableSearch")}</Table.Th>
        <Table.Th>{t("mirrors.source")}</Table.Th>
        {showSetting && <Table.Th>{t("mirrors.desiredState")}</Table.Th>}
      </Table.Tr>}>
      {list.items.map(table => <Table.Tr key={table.object_id}>
        <Table.Td>
          <Anchor component="button" type="button" ta="start" data-mirror-return={`pick-${table.object_id}`} onClick={event => {
            rememberMirrorPosition(href, event.currentTarget);
            onSelect(table.object_id);
          }}>{table.qualified_table}</Anchor>
        </Table.Td>
        <Table.Td>{table.source_name}</Table.Td>
        {showSetting && <Table.Td>{table.mirror && t(table.mirror.enabled ? "mirrors.desiredEnabled" : "mirrors.desiredDisabled")}</Table.Td>}
      </Table.Tr>)}
    </ListTable>
  </Stack>;
}

function TableSetting({ objectId, canRead, canWrite, onAccepted }: {
  objectId: string; canRead: boolean; canWrite: boolean; onAccepted?: () => void;
}) {
  const t = useTranslate();
  const { pathname, search } = useConsoleLocation();
  const originParams = new URLSearchParams(search.toString());
  originParams.set("mirrorTable", objectId);
  const origin = pathname + "?" + originParams;
  const [table, setTable] = useState<MirrorTable | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const pendingWrite = useRef<AbortController | null>(null);
  useEffect(() => () => pendingWrite.current?.abort(), []);

  const showLoadError = useEffectEvent((error: unknown, signal: AbortSignal) => {
    presentProblemNotification(t, error, { onRetry: () => {
      if (!signal.aborted) setReload(value => value + 1);
    } });
  });
  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    void listMirrorTables({ object_id: objectId, limit: 1, offset: 0 }, controller.signal).then(result => {
      if (!controller.signal.aborted) {
        setTable(result.items[0] ?? null);
        setStatus("ready");
      }
    }).catch(error => {
      if (!controller.signal.aborted) {
        setTable(null);
        setStatus("error");
        showLoadError(error, controller.signal);
      }
    });
    return () => controller.abort();
  }, [objectId, reload]);

  useEffect(() => {
    if (status === "ready") restoreMirrorPosition(origin);
  }, [origin, status]);

  async function save(enabled: boolean) {
    if (pendingWrite.current || !table || !canWrite ||
      !(enabled ? table.mirror?.can_enable : table.mirror?.can_disable)) return;
    const controller = new AbortController();
    const { signal } = controller;
    pendingWrite.current = controller;
    setSaving(true);
    try {
      const result = await setCatalogMirrorEnabled(objectId, enabled, signal);
      if (signal.aborted) return;
      setTable({ ...table, mirror: result.mirror });
      setReceipt(result.operation_id);
      presentConsoleNotification({ type: "success", title: t("mirrors.acceptedForTable", { table: table.qualified_table }) });
      onAccepted?.();
    } catch (error) {
      if (signal.aborted) return;
      setReceipt(null);
      presentProblemNotification(t, error);
      setReload(value => value + 1);
    } finally {
      if (!signal.aborted) setSaving(false);
      pendingWrite.current = null;
    }
  }

  if (status === "loading") return <PageBodySkeleton rows={4} />;
  if (status === "error") return <UnstyledButton onClick={() => setReload(value => value + 1)}>
    <StatusBadge tone="danger" labelKey="status.unloaded" />
  </UnstyledButton>;
  if (!table) return <Text>{t("mirrors.tableUnavailable")}</Text>;
  const setting = table.mirror;
  const holder = canRead ? table.snapshot_holder : null;
  const publicationWait = canRead ? table.publication_wait : null;
  const unavailable = t("mirrors.unmeasured");
  return <Stack gap="lg">
    <Title order={3}>{table.qualified_table}</Title>
    <SimpleGrid cols={{ base: 1, xs: 2 }}>
      <DisplayField label={t("mirrors.source")} value={table.source_name} />
      <DisplayField label={t("mirrors.destination")} value={table.storage_destination} />
      <DisplayField label={t("mirrors.sourceSize")} value={table.source_size_bytes == null ? unavailable : t("mirrors.bytes", { bytes: table.source_size_bytes.toLocaleString() })} />
      <DisplayField label={t("mirrors.rowEstimate")} value={table.estimated_rows?.toLocaleString() ?? unavailable} />
    </SimpleGrid>
    {setting && (canRead || canWrite) && <>
      {!setting.enabled && <Callout tone="info" title={t("mirrors.beforeEnable")}>
        <Text size="sm">{t("mirrors.enablePlan")}</Text>
        <Text size="sm" mt="xs">{t("mirrors.admissionPlan")}</Text>
      </Callout>}
      {holder && !setting.mirror_id && <MirrorWaitDependency kind="slot" dependency={holder} origin={origin} />}
      {publicationWait && !setting.mirror_id && <MirrorWaitDependency kind="publication" dependency={publicationWait} origin={origin} />}
      <MirrorSwitch enabled={setting.enabled}
        disabled={saving || !canWrite || !(setting.enabled ? setting.can_disable : setting.can_enable)}
        table={table.qualified_table} onChange={enabled => void save(enabled)} />
      {receipt && !saving && <div role="status"><Text fw={600}>{t("mirrors.accepted")}</Text><Text size="sm">{receipt}</Text></div>}
      {canRead && setting.mirror_id && <TableCopyState key={receipt} id={setting.mirror_id} origin={origin}
        initialHolder={holder} initialPublicationWait={publicationWait} />}
    </>}
  </Stack>;
}

function TableCopyState({ id, origin, initialHolder, initialPublicationWait }: {
  id: string; origin: string; initialHolder: MirrorTable["snapshot_holder"]; initialPublicationWait: MirrorTable["publication_wait"];
}) {
  const t = useTranslate();
  const live = useMirrorStatus(id);
  useEffect(() => {
    if (live.status === "ready") restoreMirrorPosition(origin);
  }, [origin, live.status]);
  if (live.status === "forbidden" || live.status === "notFound") return null;
  return <Stack gap="sm">
    {live.mirror ? <>
      <MirrorStatusFreshness stale={live.stale} lastSuccessAt={live.lastSuccessAt} refresh={live.refresh} />
      <MirrorCopySummary mirror={live.mirror} origin={origin} />
    </> : live.status === "unloaded" ?
      <UnstyledButton onClick={() => void live.refresh()}><StatusBadge tone="danger" labelKey="status.unloaded" /></UnstyledButton> :
      <>
        {initialHolder && <MirrorWaitDependency kind="slot" dependency={initialHolder} origin={origin} />}
        {initialPublicationWait && <MirrorWaitDependency kind="publication" dependency={initialPublicationWait} origin={origin} />}
        <PageBodySkeleton rows={2} />
      </>}
    <Button w="fit-content" component={ConsoleLink} data-mirror-return="detail"
      onClick={e => rememberMirrorPosition(origin, e.currentTarget)} href={mirrorDetailHref(id, origin)}>
      {t("catalog.mirror.view")}
    </Button>
  </Stack>;
}
