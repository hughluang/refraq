"use client";

import { Button, Group, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { ListTable } from "@/components/display/ListTable";
import { FormSection } from "@/components/form/FormSection";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsoleLocation } from "@/components/navigation/useConsoleNavigation";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery, type ListQuery } from "@/hooks/useListQuery";
import { SEARCH_DEBOUNCE_MS } from "@/hooks/useSearchDebounce";
import type { PageQuery } from "@/lib/pagination";
import { listFleetRuntimes, listFleetSources } from "./api";
import { LINKS, type Health, type Link } from "./diagnosticTypes";
import type { FleetOverview, OperationsScope } from "./fleetTypes";
import { operationsHref } from "./OperationsNavigation";
import { rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";

export const HEALTH_ORDER: Health[] = ["failed", "stale", "unobserved", "healthy"];
const filters = [
  { key: "health", type: "select", defaultValue: "", accept: ["", ...HEALTH_ORDER] },
  { key: "segment", type: "select", defaultValue: "", accept: ["", ...LINKS] },
] as const;

function healthHref(scope: OperationsScope, health: Health, segment?: Link) {
  return operationsHref("diagnostics", scope, { health, ...(segment ? { segment } : {}) });
}

function DiagnosticSearch({ query, label }: { query: ListQuery; label: string }) {
  const [draft, setDraft] = useState(query.search);
  const publish = useRef(query.setSearch);
  publish.current = query.setSearch;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancel = () => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => {
    setDraft(query.search);
    cancel();
  }, [query.search]);
  useEffect(() => () => cancel(), []);
  return <TextInput aria-label={label} placeholder={label} value={draft}
    onChange={event => {
      const value = event.currentTarget.value;
      setDraft(value);
      cancel();
      timer.current = setTimeout(() => { timer.current = null; publish.current(value); }, SEARCH_DEBOUNCE_MS);
    }}
    onKeyDown={event => {
      if (event.key === "Enter") {
        event.preventDefault();
        cancel();
        publish.current(draft);
      } else if (event.key === "Escape" && (draft || query.search)) {
        event.preventDefault();
        event.stopPropagation();
        cancel();
        setDraft("");
        publish.current("");
      }
    }} />;
}

type FinderProps = {
  scope: OperationsScope;
  query: ListQuery;
  health: string;
  segment: string;
  observedAt: string;
  origin: string;
  stale: boolean;
  onClear: () => void;
};

function RuntimeResults({ scope, query, health, segment, observedAt, origin, stale, onClear, refinement }: FinderProps & { refinement: URLSearchParams }) {
  const t = useTranslate();
  const { source_id, runtime_id } = scope;
  const q = query.search;
  const fetch = useCallback((page: PageQuery) => listFleetRuntimes({ ...page, source_id, runtime_id, health, segment, q }),
    [source_id, runtime_id, health, segment, q, observedAt]);
  const list = useConsolePagedList({ fetch, pageSize: 12, page: query.page, onPageChange: query.setPage,
    filtered: query.isFiltered || !!health || !!segment });
  const outdated = stale || !!list.error;
  const restored = useRef<string | null>(null);
  useEffect(() => {
    if (list.loading || restored.current === origin) return;
    restoreMirrorPosition(origin);
    restored.current = origin;
  }, [origin, list.loading]);
  return <>
    {outdated && list.items.length > 0 && <Text size="sm" role="status">{t("diagnostics.staleSnapshot")}</Text>}
    <ListTable embedded minWidth={0} list={list} columnCount={2} onClearFilters={onClear}
      head={<Table.Tr><Table.Th>{t("fleetDiagnostic.runtime")}</Table.Th><Table.Th>{t("fleetDiagnostic.affectedSources")}</Table.Th></Table.Tr>}>
      {list.items.map(runtime => <Table.Tr key={runtime.id}>
        <Table.Td><ConsoleLink href={operationsHref("diagnostics", { runtime_id: runtime.id }, refinement)}
          data-mirror-return={`runtime-${runtime.id}`} onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>
          {runtime.runtime_instance_id ?? t("fleetDiagnostic.unassigned")}
        </ConsoleLink></Table.Td>
        <Table.Td>{outdated ? "—" : `${runtime.affected_source_count} / ${runtime.source_count}`}</Table.Td>
      </Table.Tr>)}
    </ListTable>
  </>;
}

function SourceResults({ scope, query, health, segment, observedAt, origin, stale, onClear }: FinderProps) {
  const t = useTranslate();
  const { source_id, runtime_id } = scope;
  const q = query.search;
  const fetch = useCallback((page: PageQuery) => listFleetSources({ ...page, source_id, runtime_id, health, segment, q }),
    [source_id, runtime_id, health, segment, q, observedAt]);
  const list = useConsolePagedList({ fetch, pageSize: 12, page: query.page, onPageChange: query.setPage, filtered: query.isFiltered });
  const outdated = stale || !!list.error;
  const restored = useRef<string | null>(null);
  useEffect(() => {
    if (list.loading || restored.current === origin) return;
    restoreMirrorPosition(origin);
    restored.current = origin;
  }, [origin, list.loading]);
  return <>
    {outdated && list.items.length > 0 && <Text size="sm" role="status">{t("diagnostics.staleSnapshot")}</Text>}
    <ListTable embedded minWidth={0} list={list} columnCount={2} onClearFilters={onClear}
      head={<Table.Tr><Table.Th>{t("mirrors.source")}</Table.Th><Table.Th>{segment ? t(`diagnostics.link.${segment}`) : t("fleet.connectionHealth")}</Table.Th></Table.Tr>}>
      {list.items.map(source => {
        const health = segment ? source.segment_health[segment as Link] : source.health;
        return <Table.Tr key={source.id}>
          <Table.Td><ConsoleLink href={operationsHref("diagnostics", { source_id: source.id }, { checks: "1", from: origin })}
            data-mirror-return={`source-result-${source.id}`} onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>{source.name}</ConsoleLink>
            <Text size="xs" c="dimmed">{source.id}</Text></Table.Td>
          <Table.Td>{t(`diagnostics.health.${outdated && health !== "unobserved" ? "stale" : health}`)}</Table.Td>
        </Table.Tr>;
      })}
    </ListTable>
  </>;
}

export function AggregateTopology({ data, scope, stale = false, origin }: {
  data: FleetOverview; scope: OperationsScope; stale?: boolean; origin: string;
}) {
  const t = useTranslate();
  return <FormSection title={t("diagnostics.path")} description={t("fleetDiagnostic.aggregateHelp", { count: data.source_count })} columns={1}>
    <div className="diagnostic-aggregate-topology">
      {LINKS.map((link, index) => <div className="diagnostic-aggregate-segment" key={link}>
        <Text size="xs" c="dimmed">{t(`diagnostics.node.${index}`)} → {t(`diagnostics.node.${index + 1}`)}</Text>
        <Text fw={600} size="sm">{t(`diagnostics.link.${link}`)}</Text>
        <div className="diagnostic-proportions" aria-hidden="true">
          {HEALTH_ORDER.map(health => <span key={health} data-health={stale ? "unobserved" : health}
            style={{ flexGrow: stale ? Number(health === "unobserved") : data.segments[link][health] }} />)}
        </div>
        <Stack gap={4}>
          {HEALTH_ORDER.map(health => <ConsoleLink key={health} href={healthHref(scope, health, link)}
            className="diagnostic-health-link" data-health={health} data-mirror-return={`segment-${link}-${health}`}
            onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>
            <span>{t(`diagnostics.health.${health}`)}</span>
            <span>{stale ? "—" : t("fleetDiagnostic.proportion", { count: data.segments[link][health],
              percent: data.source_count ? (100 * data.segments[link][health] / data.source_count).toFixed(1) : "0.0" })}</span>
          </ConsoleLink>)}
        </Stack>
      </div>)}
    </div>
  </FormSection>;
}

export function FleetDiagnosticExplorer({ data, scope, origin, stale = false }: {
  data: FleetOverview; scope: OperationsScope; origin: string; stale?: boolean;
}) {
  const t = useTranslate();
  const sourceQuery = useListQuery({ filters, pageKey: "source_results_page" });
  const runtimeQuery = useListQuery({ search: "runtime_q", pageKey: "runtime_results_page" });
  const health = sourceQuery.select("health");
  const segment = sourceQuery.select("segment");
  const { search } = useConsoleLocation();
  const source_id = scope.source_id;
  const runtime_id = scope.runtime_id;
  const q = sourceQuery.search;
  const refinement = new URLSearchParams();
  if (health) refinement.set("health", health);
  if (segment) refinement.set("segment", segment);
  if (q) refinement.set("q", q);
  const expand = operationsHref("diagnostics", {}, refinement);
  const sourceKey = JSON.stringify([source_id, runtime_id, health, segment, q, sourceQuery.page]);
  const runtimeKey = JSON.stringify([source_id, runtime_id, health, segment, runtimeQuery.search, runtimeQuery.page]);
  return <Stack gap="xl">
    <FormSection title={t("fleetDiagnostic.sourceHealth")} description={t("fleetDiagnostic.sourceHealthHelp")} columns={1}>
      <Group gap="sm">{HEALTH_ORDER.map(value => <Button key={value} component={ConsoleLink}
        href={healthHref(scope, value)} variant={health === value && !segment ? "light" : "subtle"} size="sm"
        data-mirror-return={`source-health-${value}`} onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>
        {t(`diagnostics.health.${value}`)}: {stale ? "—" : data.health[value]}
      </Button>)}</Group>
    </FormSection>
    {data.source_count > 8 && <AggregateTopology data={data} scope={scope} origin={origin} stale={stale} />}
    <FormSection title={t("fleetDiagnostic.findAffected")} columns={1}>
      <Group gap="sm" align="end">
        <Select label={t("fleet.healthFilter")} placeholder={t("fleet.allHealth")} clearable value={health || null}
          data={HEALTH_ORDER.map(value => ({ value, label: t(`diagnostics.health.${value}`) }))}
          onChange={value => { sourceQuery.setFilter("health", value ?? ""); runtimeQuery.setPage(1); }} />
        <Select label={t("fleetDiagnostic.segmentFilter")} placeholder={t("fleetDiagnostic.worstLink")} clearable value={segment || null}
          data={LINKS.map(value => ({ value, label: t(`diagnostics.link.${value}`) }))}
          onChange={value => { sourceQuery.setFilter("segment", value ?? ""); runtimeQuery.setPage(1); }} />
        {(sourceQuery.isFiltered || runtimeQuery.isFiltered) && <Button size="sm" variant="subtle" onClick={() => {
          sourceQuery.clear(); runtimeQuery.clear();
        }}>{t("common.filters.clear")}</Button>}
      </Group>
      <div className="diagnostic-finders">
        <Stack gap="sm" miw={0}>
          <Text fw={600}>{t("diagnostics.runtimeGroups")}</Text>
          <DiagnosticSearch query={runtimeQuery} label={t("fleetDiagnostic.searchRuntimes")} />
          <RuntimeResults key={runtimeKey} scope={scope} query={runtimeQuery} health={health} segment={segment}
            observedAt={data.observed_at} origin={origin} stale={stale} refinement={refinement} onClear={() => {
            runtimeQuery.clear(); sourceQuery.setFilter("health", ""); sourceQuery.setFilter("segment", "");
          }} />
        </Stack>
        <Stack gap="sm" miw={0}>
          <Group justify="space-between"><Text fw={600}>{t("diagnostics.sources")}</Text>
            {(source_id || runtime_id) && <Button component={ConsoleLink} href={expand} size="xs" variant="subtle">{t("fleet.searchEntireFleet")}</Button>}
          </Group>
          <DiagnosticSearch query={sourceQuery} label={t("fleet.searchSources")} />
          <SourceResults key={sourceKey} scope={scope} query={sourceQuery} health={health} segment={segment}
            observedAt={data.observed_at} origin={origin} stale={stale} onClear={sourceQuery.clear} />
        </Stack>
      </div>
      {search.get("health") && <Text size="xs" c="dimmed">{segment ? t("fleetDiagnostic.segmentHelp") : t("fleetDiagnostic.worstLinkHelp")}</Text>}
    </FormSection>
  </Stack>;
}
