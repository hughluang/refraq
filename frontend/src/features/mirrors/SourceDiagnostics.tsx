"use client";

import { Badge, Button, Drawer, Group, Stack, Table, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";
import { CheckIcon, ClockIcon, CloseIcon, InfoIcon } from "@/components/icons";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { FormSection } from "@/components/form/FormSection";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsoleLocation, useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { getFleetOverview, getSourceDiagnostics } from "./api";
import { LINKS, type Diagnostics, type Health, type Round } from "./diagnosticTypes";
import { FleetDiagnosticExplorer } from "./FleetDiagnostics";
import { OperationsNavigation, operationsHref, operationsScope } from "./OperationsNavigation";
import { mirrorDetailHref, mirrorReturnHref, rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";
import { useDiagnosticRead } from "./useDiagnosticRead";
import "./diagnostics.css";

function HealthLabel({ health }: { health: Health }) {
  const t = useTranslate();
  return <Badge className="diagnostic-health" data-health={health} color={{ healthy: "green", failed: "red", stale: "orange", unobserved: "gray" }[health]} variant="light">{t(`diagnostics.health.${health}`)}</Badge>;
}

function Pages({ offset, size, total, change, label }: { offset: number; size: number; total: number; change: (offset: number) => void; label: string }) {
  const t = useTranslate();
  if (total <= size) return null;
  return <Group gap="sm" role="group" aria-label={label}>
    <Button size="xs" variant="subtle" disabled={offset === 0} onClick={() => change(Math.max(0, offset - size))}>{t("diagnostics.previous")}</Button>
    <Text size="sm">{offset + 1}–{Math.min(offset + size, total)} / {total}</Text>
    <Button size="xs" variant="subtle" disabled={offset + size >= total} onClick={() => change(offset + size)}>{t("diagnostics.next")}</Button>
  </Group>;
}

export function DiagnosticContent({ data, origin, stale = false, page, selectSource, showPath = true, initialSource, closeChecks }: {
  data: Diagnostics; origin: string; stale?: boolean;
  page: (key: "source_offset" | "runtime_offset" | "assignment_offset", value: number) => void;
  selectSource: (id: string) => string;
  showPath?: boolean; initialSource?: string; closeChecks?: () => void;
}) {
  const t = useTranslate();
  const [selection, setSelection] = useState<{ source: string; round?: Round } | null>(null);
  useEffect(() => { setSelection(initialSource ? { source: initialSource } : null); }, [initialSource]);
  const selected = data.sources.find(source => source.id === selection?.source);
  const checks = selection?.round?.checks ?? selected?.checks ?? [];
  const health = (value: Health): Health => stale && value !== "unobserved" ? "stale" : value;
  return <Stack gap="xl">
    {stale && <Text role="status">{t("diagnostics.staleSnapshot")}</Text>}
    {showPath && <FormSection title={t("diagnostics.path")} description={t("diagnostics.pathHelp")} columns={1}>
      <Group gap="md">{(["healthy", "failed", "stale", "unobserved"] as Health[]).map(state => <Group key={state} gap="xs">
        <HealthLabel health={state} /><Text size="sm">{stale ? "—" : data.link_counts[state]}</Text>
      </Group>)}</Group>
      <div className="diagnostic-topology">
        {data.sources.map(source => <div className="diagnostic-source" key={source.id}>
          <div className="diagnostic-source-name"><Text fw={600}>{source.name}</Text><Text size="xs" c="dimmed">{source.id}</Text></div>
          {LINKS.map((link, index) => {
            const check = source.checks.find(item => item.link === link)!;
            return <button key={link} type="button" className="diagnostic-segment" data-health={health(check.health)}
              aria-label={t("diagnostics.segmentLabel", { source: source.name, link: t(`diagnostics.link.${link}`), health: t(`diagnostics.health.${health(check.health)}`) })}
              onClick={() => setSelection({ source: source.id })}>
              <Text size="xs" c="dimmed">{t(`diagnostics.node.${index}`)} → {t(`diagnostics.node.${index + 1}`)}</Text>
              <Text size="sm" fw={500}>{t(`diagnostics.link.${link}`)}</Text><HealthLabel health={health(check.health)} />
            </button>;
          })}
          <div className="diagnostic-history" role="group" aria-label={t("diagnostics.history", { source: source.name })}>
            <Text size="xs">{t("diagnostics.last16")}</Text>
            <div className="diagnostic-history-slots">{source.history.map((round, index) => round ?
              <button key={round.id} type="button" className="diagnostic-history-slot" data-health={round.health}
                title={t("diagnostics.roundLabel", { at: round.at, health: t(`diagnostics.health.${round.health}`) })}
                aria-label={t("diagnostics.roundLabel", { at: round.at, health: t(`diagnostics.health.${round.health}`) })}
                onClick={() => setSelection({ source: source.id, round })}>{(() => {
                  const Icon = { healthy: CheckIcon, failed: CloseIcon, stale: ClockIcon, unobserved: InfoIcon }[round.health];
                  return <Icon size={12} aria-hidden="true" />;
                })()}</button> :
              <span key={`empty-${index}`} className="diagnostic-history-slot" data-health="empty" title={t("diagnostics.noRound")} aria-label={t("diagnostics.noRound")}>—</span>)}</div>
          </div>
        </div>)}
      </div>
      {!data.sources.length && <Text>{t("diagnostics.noSources")}</Text>}
      <Pages offset={data.source_offset} size={8} total={data.matching_sources} label={t("diagnostics.sources")}
        change={value => page("source_offset", value)} />
    </FormSection>}
    <FormSection title={t("diagnostics.traffic")} description={t("diagnostics.trafficHelp", { count: data.mirror_count })} columns={1}>
      <div className="diagnostic-metrics">{Object.entries(data.summary).map(([key, metric]) => <div key={key} className="diagnostic-metric">
        <Text fw={500}>{t(`diagnostics.${key}`)}</Text>
        <Text>{metric.value == null ? t("diagnostics.unavailable") : metric.value.toLocaleString()}</Text>
        <Text size="sm">{t("diagnostics.coverage", { sampled: metric.sampled, total: data.mirror_count, missing: metric.missing })}</Text>
        <Text size="xs">{t("diagnostics.interval")}: <Instant value={metric.interval_start} /> — <Instant value={metric.interval_end} /></Text>
        <Text size="xs">{t("diagnostics.observations")}: <Instant value={metric.oldest_observation} /> — <Instant value={metric.newest_observation} /></Text>
      </div>)}</div>
      <Text size="sm" c="dimmed">{t("diagnostics.backlogHelp")}</Text>
      {Object.entries(data.states).map(([kind, states]) => <Group key={kind} gap="sm">
        <Text size="sm" fw={500}>{t(`diagnostics.state.${kind}`)}</Text>
        {Object.entries(states).map(([state, count]) => <Text size="sm" key={state}>{t(`diagnostics.state.${state}`)}: {count}</Text>)}
      </Group>)}
      <details><summary>{t("diagnostics.tableIntervals")}</summary>
        <div className="diagnostic-table-scroll"><Table mt="sm"><Table.Thead><Table.Tr>
          {["table", "interval", "observedAt", "validity"].map(key => <Table.Th key={key}>{t(`diagnostics.${key}`)}</Table.Th>)}
        </Table.Tr></Table.Thead><Table.Tbody>{data.intervals.map(item => <Table.Tr key={item.mirror_id}>
          <Table.Td><ConsoleLink href={mirrorDetailHref(item.mirror_id, origin)} data-mirror-return={item.mirror_id}
            onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>{item.qualified_table}</ConsoleLink></Table.Td>
          <Table.Td><Instant value={item.interval_start} /> — <Instant value={item.interval_end} /></Table.Td>
          <Table.Td><Instant value={item.observed_at} /></Table.Td><Table.Td><HealthLabel health={!item.observed_at ? "unobserved" : stale || item.stale ? "stale" : "healthy"} /></Table.Td>
        </Table.Tr>)}</Table.Tbody></Table></div>
      </details>
    </FormSection>
    <details className="diagnostic-runtimes"><summary>{t("diagnostics.runtimes", { count: data.total_runtimes })}</summary>
      <Stack gap="lg" mt="md">{data.runtimes.map(runtime => <FormSection key={runtime.id} title={runtime.id}>
        <DisplayField label={t("diagnostics.heartbeat")} value={<Group gap="xs"><HealthLabel health={health(runtime.heartbeat_health)} /><Instant value={runtime.heartbeat?.observed_at} /></Group>} />
        <DisplayField label={t("diagnostics.cycle")} value={<Group gap="xs"><HealthLabel health={health(runtime.cycle_health)} /><Instant value={runtime.cycle?.observed_at} /></Group>} />
        <DisplayField label={t("diagnostics.completedAt")} value={<Instant value={runtime.cycle?.last_completed_at} />} />
        <DisplayField label={t("diagnostics.duration")} value={runtime.cycle?.last_duration_seconds == null ? t("diagnostics.unavailable") : t("diagnostics.seconds", { value: runtime.cycle.last_duration_seconds.toFixed(2) })} />
        <DisplayField label={t("diagnostics.wait")} value={runtime.end_of_cycle_wait_seconds == null ? t("diagnostics.unavailable") : t("diagnostics.seconds", { value: runtime.end_of_cycle_wait_seconds })} />
        <div className="diagnostic-assignments">
          <Text size="sm">{t("diagnostics.fullCycle", { count: runtime.total_sources })}</Text>
          {runtime.assignment_stale && <Text size="sm">{t("diagnostics.staleAssignments")}</Text>}
          <ol start={runtime.assignment_offset + 1}>{runtime.source_ids.map(id => <li key={id}><ConsoleLink href={selectSource(id)} data-mirror-return={`assignment-${id}`}
            onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>{id}</ConsoleLink></li>)}</ol>
          <Pages offset={runtime.assignment_offset} size={8} total={runtime.total_sources} label={t("diagnostics.assignments")}
            change={value => page("assignment_offset", value)} />
        </div>
      </FormSection>)}
        <Pages offset={data.runtime_offset} size={3} total={data.total_runtimes} label={t("diagnostics.runtimeGroups")}
          change={value => page("runtime_offset", value)} />
      </Stack>
    </details>
    <Drawer opened={!!selected} onClose={() => { setSelection(null); closeChecks?.(); }} title={t("diagnostics.checksFor", { source: selected?.name ?? "" })} closeButtonProps={{ "aria-label": t("mirrors.closeDrawer") }} position="right" size="lg">
      {selected && <Stack gap="xl">
        {selection?.round ? <Text>{t("diagnostics.historicalRound")}: <Instant value={selection.round.at} /></Text> :
          <Text size="sm">{t("diagnostics.sharedChecks")}</Text>}
        {checks.map(check => <Stack key={check.link} gap="xs">
          <Group justify="space-between"><Title order={3}>{t(`diagnostics.link.${check.link}`)}</Title><HealthLabel health={selection?.round ? check.health : health(check.health)} /></Group>
          <DisplayField label={t("diagnostics.observedAt")} value={<Instant value={check.observed_at} />} />
          <DisplayField label={t("diagnostics.validUntil")} value={<Instant value={check.valid_until} />} />
          <DisplayField label={t("diagnostics.lastSuccess")} value={<Instant value={check.last_success_at} />} />
          {check.error_code && <><DisplayField label={t("diagnostics.failureAt")} value={<Instant value={check.failure_at} />} />
            <DisplayField label={t("diagnostics.errorCode")} value={check.error_code} />
            <Text size="sm">{t(`diagnostics.nextCheck.${check.link}`)}</Text></>}
        </Stack>)}
      </Stack>}
    </Drawer>
  </Stack>;
}

export function SourceDiagnostics() {
  const t = useTranslate();
  const { search, href } = useConsoleLocation();
  const scope = operationsScope(search);
  const query = new URLSearchParams();
  if (scope.source_id) query.set("source_id", scope.source_id);
  else if (scope.runtime_id) query.set("runtime_id", scope.runtime_id);
  for (const key of ["source_offset", "runtime_offset", "assignment_offset"])
    if (search?.get(key)) query.set(key, search.get(key)!);
  const read = useDiagnosticRead(query.toString(), signal => getSourceDiagnostics(query, signal));
  const fleetKey = `${scope.source_id ?? ""}/${scope.runtime_id ?? ""}`;
  const fleet = useDiagnosticRead(`fleet-diagnostics/${fleetKey}`, signal => getFleetOverview(scope, signal));
  const origin = mirrorReturnHref(search?.get("from") ?? null);
  const navigate = (key: string, value: string) => {
    const next = new URLSearchParams(search?.toString());
    next.set(key, value);
    return `/console/mirrors/diagnostics?${next}`;
  };
  const { replace } = useConsoleNavigation();
  const status = (["forbidden", "notFound", "unloaded", "loading"] as const)
    .find(value => read.status === value || fleet.status === value) ?? "ready";
  const refresh = () => { void read.refresh(); void fleet.refresh(); };
  useEffect(() => { if (read.status === "ready") restoreMirrorPosition(href); }, [read.status, href]);
  return <PageChrome title={t("diagnostics.title")} description={t("diagnostics.description")} status={status}
    forbiddenReason="mirror:read" onRetry={refresh}
    actions={<HeaderActions navigation={<>
      <Button component={ConsoleLink} href={origin} size="sm" variant="light">{t("diagnostics.back")}</Button>
      <Button size="sm" variant="light" onClick={refresh}>{t("common.refresh")}</Button>
    </>} />} tabs={<OperationsNavigation view="diagnostics" scope={scope} />}>
    {status !== "forbidden" && <Stack gap="xl">
      {fleet.value && <FleetDiagnosticExplorer data={fleet.value} scope={scope} origin={href} stale={fleet.stale} />}
      {read.value && <DiagnosticContent key={fleetKey} data={read.value} origin={href} stale={read.stale}
        showPath={read.value.source_count <= 8} initialSource={search.get("checks") === "1" ? scope.source_id : undefined}
        closeChecks={() => {
          if (!search.has("checks")) return;
          const next = new URLSearchParams(search.toString());
          next.delete("checks");
          replace(`/console/mirrors/diagnostics${next.size ? `?${next}` : ""}`);
        }}
        page={(key, offset) => replace(navigate(key, String(offset)))}
        selectSource={id => operationsHref("diagnostics", { source_id: id }, { checks: "1", from: href })} />}
    </Stack>}
  </PageChrome>;
}
