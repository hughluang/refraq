"use client";

import { Button, Group, Progress, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useEffect, type MouseEvent, type ReactNode } from "react";
import { Instant } from "@/components/display/Instant";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsoleLocation } from "@/components/navigation/useConsoleNavigation";
import { useListQuery } from "@/hooks/useListQuery";
import { getFleetOverview, getFleetThroughput } from "./api";
import { FLEET_STATES, type FleetOverview as Overview, type OperationsScope } from "./fleetTypes";
import { decimalBytes, fleetPercent } from "./fleetFormat";
import { FleetThroughputChart } from "./FleetThroughputChart";
import { OperationsNavigation, operationsHref, operationsScope } from "./OperationsNavigation";
import { rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";
import { useDiagnosticRead } from "./useDiagnosticRead";
import classes from "./Operations.module.css";

const filters = [
  { key: "hours", type: "select", defaultValue: "6", accept: ["1", "6", "24"] },
  { key: "rank", type: "select", defaultValue: "size", accept: ["size", "attention"] },
] as const;

export function FleetOverview() {
  const t = useTranslate();
  const { href, search } = useConsoleLocation();
  const scope = operationsScope(search);
  const query = useListQuery({ search: false, filters });
  const rank = query.select("rank"), hours = query.select("hours");
  const key = JSON.stringify(scope);
  const fleet = useDiagnosticRead(`${key}:${rank}`, signal => getFleetOverview({ ...scope, rank }, signal));
  const traffic = useDiagnosticRead(`${key}:${hours}`, signal => getFleetThroughput({ ...scope, hours: Number(hours) }, signal));
  const { data: catalog } = useCan({ resource: "catalog", action: "list" });
  useEffect(() => { if (fleet.status === "ready") restoreMirrorPosition(href); }, [fleet.status, href]);
  return <PageChrome title={t("fleet.overview")} description={t("fleet.overviewHelp")} status={fleet.status}
    forbiddenReason="mirror:read" onRetry={() => void fleet.refresh()}
    tabs={<OperationsNavigation view="overview" scope={scope} />}
    actions={<HeaderActions navigation={<>
      {catalog?.can && <Button component={ConsoleLink} href={`/console/catalog${scope.source_id ? `?source=${encodeURIComponent(scope.source_id)}` : ""}`} size="sm" variant="light">{t("catalog.title")}</Button>}
      <Button size="sm" variant="light" onClick={() => { void fleet.refresh(); void traffic.refresh(); }}>{t("common.refresh")}</Button>
    </>} />}>
    {fleet.value && <Stack gap="xl">
      {fleet.stale && <Text role="status" size="sm">{t("diagnostics.staleSnapshot")}</Text>}
      <FleetOverviewContent data={fleet.value} scope={scope} origin={href} rank={rank} onRankChange={value => query.setFilter("rank", value)}
        throughput={traffic.status === "forbidden" ? <Text role="status">{t("fleet.throughputForbidden")}</Text> : <>
          <FleetThroughputChart data={traffic.value} hours={hours} onHoursChange={value => query.setFilter("hours", value)} stale={traffic.stale} />
          {!traffic.value && <Button variant="subtle" size="xs" w="fit-content" onClick={() => void traffic.refresh()}>{t(traffic.status === "loading" ? "fleet.loadingThroughput" : "fleet.retryThroughput")}</Button>}
        </>} />
      <Text size="xs" c="dimmed">{t("fleet.observedAt")}: <Instant value={fleet.value.observed_at} /></Text>
    </Stack>}
  </PageChrome>;
}

export function FleetOverviewContent({ data, scope, origin, rank, onRankChange, throughput }: {
  data: Overview; scope: OperationsScope; origin: string; rank: string; onRankChange: (value: string) => void;
  throughput?: ReactNode;
}) {
  const t = useTranslate();
  const inventory = (extra: Record<string, string> = {}) => operationsHref("inventory", scope, extra);
  const remember = (event: MouseEvent<HTMLAnchorElement>) => rememberMirrorPosition(origin, event.currentTarget);
  const healthTotal = Object.values(data.health).reduce((sum, count) => sum + count, 0);
  const copyPercent = data.snapshot.scanned_bytes != null && data.snapshot.source_size_bytes
    ? Math.min(100, data.snapshot.scanned_bytes / data.snapshot.source_size_bytes * 100) : 0;
  return <>
    <section className={classes.totals} aria-label={t("fleet.totals")}>
      <div><Text c="dimmed" size="sm">{t("fleet.mirrors")}</Text><ConsoleLink className={classes.totalValue} href={inventory()} data-mirror-return="fleet-total-mirrors" onClick={remember}>{data.mirror_count.toLocaleString()}</ConsoleLink><Text size="sm">{t("fleet.sourceCount", { count: data.source_count })}</Text></div>
      <div><Text c="dimmed" size="sm">{t("fleet.sourceSize")}</Text><Text className={classes.totalValue}>{decimalBytes(data.source_size.value)}</Text><Text size="sm">{t("fleet.estimatedRows")}: {data.estimated_rows.value?.toLocaleString() ?? t("diagnostics.unavailable")}</Text>
        {(data.source_size.missing > 0 || data.estimated_rows.missing > 0) && <Text size="xs" c="dimmed">{t("fleet.missingEstimates", { bytes: data.source_size.missing, rows: data.estimated_rows.missing })}</Text>}</div>
      <div><Text c="dimmed" size="sm">{t("fleet.published")}</Text><ConsoleLink className={classes.totalValue} href={inventory({ published_only: "1" })} data-mirror-return="fleet-total-published" onClick={remember}>{data.published_count.toLocaleString()}</ConsoleLink><Text size="sm">{fleetPercent(data.published_percent)} · {t("fleet.retainedIncluded")}</Text></div>
      <div><Text c="dimmed" size="sm">{t("fleet.attention")}</Text><ConsoleLink className={classes.totalValue} href={inventory({ grouped_state: "attention" })} data-mirror-return="fleet-total-attention" onClick={remember}>{data.attention_count.toLocaleString()}</ConsoleLink><Text size="sm">{t("fleet.openAttention")}</Text></div>
    </section>
    {throughput}
    <div className={classes.overviewColumns}>
      <section className={classes.section} aria-labelledby="fleet-status-title">
        <Title id="fleet-status-title" order={2} size="h4">{t("fleet.synchronization")}</Title>
        <div className={classes.states}>{FLEET_STATES.map(state => <ConsoleLink key={state} href={inventory({ grouped_state: state })} className={classes.stateLink} data-mirror-return={`fleet-state-${state}`} onClick={remember}>
          <Text span size="sm">{t(`fleet.state.${state}`)}</Text>{" "}<Text span fw={600}>{data.states[state].count.toLocaleString()}</Text>{" "}<Text span size="xs" c="dimmed">{fleetPercent(data.states[state].percent)}</Text>
        </ConsoleLink>)}</div>
        <div className={classes.snapshot}>
          <Title order={3} size="h5">{t("fleet.copyProgress")}</Title>
          <Text size="sm" mt="xs">{data.snapshot.sampled ? `${decimalBytes(data.snapshot.scanned_bytes)} / ${decimalBytes(data.snapshot.source_size_bytes)}` : t("fleet.noScanSamples")}</Text>
          <Progress value={copyPercent} mt="xs" aria-label={t("fleet.copyProgress")} />
          <Group gap="lg" mt="xs"><Text size="xs">{t("fleet.sampledTables", { count: data.snapshot.sampled })}</Text><Text size="xs">{t("fleet.queuedTables", { count: data.snapshot.queued })}</Text>
            {data.snapshot.missing > 0 && <Text size="xs">{t("fleet.missingScanSamples", { count: data.snapshot.missing })}</Text>}</Group>
          <Text size="xs" c="dimmed" mt="xs">{t("fleet.copyProgressHelp")}</Text>
        </div>
      </section>
      <section className={classes.section} aria-labelledby="fleet-health-title">
        <Group justify="space-between"><Title id="fleet-health-title" order={2} size="h4">{t("fleet.connectionHealth")}</Title>
          <ConsoleLink href={operationsHref("diagnostics", scope)} data-mirror-return="fleet-topology" onClick={remember}>{t("fleet.openTopology")}</ConsoleLink></Group>
        <Text size="xl" fw={600} mt="sm">{fleetPercent(healthTotal ? data.health.healthy / healthTotal * 100 : null)} <Text span size="sm" fw={400}>{t("fleet.healthySources")}</Text></Text>
        <Text size="xs" c="dimmed">{t("fleet.healthHelp")}</Text>
        <div className={classes.healthTotals}>{(["failed", "stale", "unobserved", "healthy"] as const).map(health => <ConsoleLink
          key={health} href={operationsHref("diagnostics", scope, { health })} className={classes.healthLink} data-health={health} data-mirror-return={`fleet-health-${health}`} onClick={remember}>
          <Text span size="sm">{t(`diagnostics.health.${health}`)}</Text>{" "}<Text span fw={600}>{data.health[health].toLocaleString()}</Text>
        </ConsoleLink>)}</div>
      </section>
    </div>
    <section className={classes.section} aria-labelledby="fleet-ranking-title">
      <Group justify="space-between" gap="sm"><div><Title id="fleet-ranking-title" order={2} size="h4">{t("fleet.sourceComparison")}</Title><Text size="sm" c="dimmed">{t("fleet.rankingHelp")}</Text></div>
        <SegmentedControl size="xs" value={rank} onChange={onRankChange} aria-label={t("fleet.rankMetric")}
          data={[{ value: "size", label: t("fleet.sourceSize") }, { value: "attention", label: t("fleet.attention") }]} /></Group>
      <div className={classes.ranking}>{data.ranking.map(source => {
        const value = rank === "attention" ? source.attention_count : source.source_size.value;
        const max = Math.max(1, ...data.ranking.map(item => rank === "attention" ? item.attention_count : item.source_size.value ?? 0));
        return <ConsoleLink key={source.id} href={operationsHref("overview", { source_id: source.id }, rank === "attention" ? { rank, grouped_state: "attention" } : { rank })}
          className={classes.rankLink} data-mirror-return={`ranking-${source.id}`} onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>
          <span className={classes.rankName}>{source.name}<Text span size="xs" c="dimmed">{source.id}</Text></span>
          <span className={classes.rankTrack} aria-hidden="true"><span style={{ width: `${(value ?? 0) / max * 100}%` }} /></span>
          <Text span size="sm" ta="right">{rank === "attention" ? value?.toLocaleString() : decimalBytes(value)}</Text>
        </ConsoleLink>;
      })}</div>
      {data.ranking_total > 8 && <Text size="sm" mt="sm">{t("fleet.rankingCount", { shown: data.ranking.length, total: data.ranking_total })} · <ConsoleLink href={operationsHref("overview", scope, { choose_source: "1" })} data-mirror-return="fleet-rank-find" onClick={remember}>{t("fleet.findSource")}</ConsoleLink></Text>}
      {!data.ranking.length && <Text size="sm" mt="sm">{t("fleet.empty")}</Text>}
    </section>
  </>;
}
