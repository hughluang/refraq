"use client";

import { Button, Drawer, Group, Select, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useEffect } from "react";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsoleLocation, useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";
import { listFleetSources } from "./api";
import type { OperationsScope } from "./fleetTypes";
import { rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";
import classes from "./Operations.module.css";

export type OperationsView = "overview" | "inventory" | "diagnostics";
const paths: Record<OperationsView, string> = {
  overview: "/console/mirrors", inventory: "/console/mirrors/inventory", diagnostics: "/console/mirrors/diagnostics",
};

export function operationsScope(search: Pick<URLSearchParams, "get">): OperationsScope {
  const source_id = search.get("source_id") || undefined;
  return source_id ? { source_id } : { runtime_id: search.get("runtime_id") || undefined };
}

export function operationsHref(view: OperationsView, scope: OperationsScope = {}, extra?: URLSearchParams | Record<string, string>) {
  const query = new URLSearchParams(extra);
  query.delete("source_id");
  query.delete("runtime_id");
  if (scope.source_id) query.set("source_id", scope.source_id);
  else if (scope.runtime_id) query.set("runtime_id", scope.runtime_id);
  return paths[view] + (query.size ? `?${query}` : "");
}

const pickerFilters = [
  { key: "source_health", type: "select", defaultValue: "", accept: ["", "failed", "stale", "unobserved", "healthy"] },
  { key: "all_sources", type: "select", defaultValue: "", accept: ["", "1"] },
] as const;

export function OperationsNavigation({ view, scope }: { view: OperationsView; scope: OperationsScope }) {
  const t = useTranslate();
  const { search, href } = useConsoleLocation();
  const { push } = useConsoleNavigation();
  const opened = search.get("choose_source") === "1";
  const clean = new URLSearchParams(search.toString());
  for (const key of ["choose_source", "source_query", "source_page", "source_health", "all_sources", "from"]) clean.delete(key);
  const choose = new URLSearchParams(clean);
  choose.set("choose_source", "1");
  function viewQuery(item: OperationsView) {
    const next = new URLSearchParams();
    const keys = item === "inventory" && view !== "diagnostics" ? ["q", "grouped_state", "published_only", "cause", "sort", "page"]
      : item === "overview" && view === "overview" ? ["hours", "rank"] : [];
    for (const key of keys) if (clean.has(key)) next.set(key, clean.get(key)!);
    return next;
  }
  return <Stack gap="sm">
    <nav aria-label={t("fleet.navigation")} className={classes.navigation}>
      {(["overview", "inventory", "diagnostics"] as const).map(item => <ConsoleLink key={item}
        href={operationsHref(item, scope, viewQuery(item))} aria-current={item === view ? "page" : undefined}>{t(`fleet.${item}`)}</ConsoleLink>)}
    </nav>
    <Group gap="sm" className={classes.scope}>
      <Text size="sm" fw={500}>{t("fleet.scope")}: {scope.source_id || scope.runtime_id || t("fleet.allSources")}</Text>
      {(scope.source_id || scope.runtime_id) && <Button component={ConsoleLink} href={operationsHref(view)} variant="subtle" size="xs">{t("fleet.entireFleet")}</Button>}
      <Button component={ConsoleLink} href={operationsHref(view, scope, choose)} size="xs" variant="light"
        data-mirror-return="choose-source" onClick={event => rememberMirrorPosition(href, event.currentTarget)}>{t("fleet.findSource")}</Button>
    </Group>
    <Drawer opened={opened} onClose={() => push(operationsHref(view, scope, clean))}
      title={t("fleet.findSource")} closeButtonProps={{ "aria-label": t("mirrors.closeDrawer") }} position="right" size="lg">
      {opened && <FleetSourcePicker view={view} scope={scope} origin={href} base={clean} />}
    </Drawer>
  </Stack>;
}

function FleetSourcePicker({ view, scope, origin, base }: {
  view: OperationsView; scope: OperationsScope; origin: string; base: URLSearchParams;
}) {
  const t = useTranslate();
  const query = useListQuery({ search: "source_query", pageKey: "source_page", filters: pickerFilters });
  const health = query.select("source_health");
  const all = query.select("all_sources") === "1";
  const source = all ? undefined : scope.source_id;
  const runtime = all ? undefined : scope.runtime_id;
  const q = query.search;
  const fetch = useCallback((page: PageQuery) => listFleetSources({ ...page, source_id: source, runtime_id: runtime, q, health }), [source, runtime, q, health]);
  const list = useConsolePagedList({ fetch, pageSize: 12, page: query.page, onPageChange: query.setPage, filtered: query.isFiltered });
  useEffect(() => { if (!list.loading) restoreMirrorPosition(origin); }, [origin, list.loading]);
  const next = new URLSearchParams(base);
  for (const key of ["page", "cause", "source_results_page", "runtime_results_page", "source_offset", "runtime_offset", "assignment_offset"])
    next.delete(key);
  if (view === "diagnostics") next.set("checks", "1");
  return <Stack gap="md">
    {!all && (scope.source_id || scope.runtime_id) && <Button variant="subtle" size="sm" onClick={() => query.setFilter("all_sources", "1")}>{t("fleet.searchEntireFleet")}</Button>}
    <ListToolbar query={query} searchPlaceholder={t("fleet.searchSources")} extra={<Select
      aria-label={t("fleet.healthFilter")} clearable placeholder={t("fleet.allHealth")} value={health || null}
      data={["failed", "stale", "unobserved", "healthy"].map(value => ({ value, label: t(`diagnostics.health.${value}`) }))}
      onChange={value => query.setFilter("source_health", value ?? "")} />} />
    <ListTable embedded minWidth={0} list={list} columnCount={2} onClearFilters={query.clear}
      head={<Table.Tr><Table.Th>{t("mirrors.source")}</Table.Th><Table.Th>{t("fleet.connectionHealth")}</Table.Th></Table.Tr>}>
      {list.items.map(source => <Table.Tr key={source.id}>
        <Table.Td><ConsoleLink href={operationsHref(view, { source_id: source.id }, next)} data-mirror-return={`source-${source.id}`}
          onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>{source.name}</ConsoleLink><Text size="xs" c="dimmed">{source.id}</Text></Table.Td>
        <Table.Td>{t(`diagnostics.health.${source.health}`)}</Table.Td>
      </Table.Tr>)}
    </ListTable>
  </Stack>;
}
