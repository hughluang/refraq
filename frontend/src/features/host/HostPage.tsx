"use client";

import { Button, Checkbox, Group, NativeSelect, Text, Title } from "@mantine/core";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageTabs } from "@/components/layout/consoleTabs";
import { PageChrome } from "@/components/layout/PageChrome";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { readHost } from "@/features/host/api";
import { formatHostBytes, formatHostMetric, formatHostNumber } from "@/features/host/format";
import { HostChart } from "@/features/host/HostChart";
import type { HostRead, HostSpan, PostgresChart } from "@/features/host/types";
import { useEntryZone, useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import { isSessionExpiredError } from "@/lib/api";

import classes from "./HostPage.module.css";

const PANELS = ["overview", "storage", "postgres", "services"] as const;
const FILTERS = [
  { key: "span", type: "select" as const, defaultValue: "day", accept: ["hour", "day", "retained"] },
  { key: "tab", type: "select" as const, defaultValue: "overview", accept: PANELS },
];
const POSTGRES_CHARTS: { key: string; field: keyof PostgresChart }[] = [
  { key: "host.postgres.backends", field: "backends" },
  { key: "host.postgres.idleInTransaction", field: "idle_in_transaction" },
  { key: "host.postgres.idleInTransactionAborted", field: "idle_in_transaction_aborted" },
  { key: "host.postgres.checkpointTimed", field: "checkpoint_timed" },
  { key: "host.postgres.checkpointRequested", field: "checkpoint_requested" },
  { key: "host.postgres.checkpointWrite", field: "checkpoint_write_time" },
  { key: "host.postgres.checkpointSync", field: "checkpoint_sync_time" },
  { key: "host.postgres.checkpointBuffers", field: "checkpoint_buffers_written" },
  { key: "host.postgres.tempFiles", field: "temp_files" },
  { key: "host.postgres.tempBytes", field: "temp_bytes" },
];

type Phase = "loading" | "ready" | "failed";

export function HostPage() {
  const t = useTranslate();
  const locale = useGetLocale()() ?? "en-US";
  const showInstant = useShowInstant();
  const zone = useEntryZone();
  const query = useListQuery({ search: false, filters: FILTERS });
  const span = query.select("span") as HostSpan;
  const panel = query.select("tab");
  const countLabel = (value: number | null) => formatHostNumber(value, locale);
  const byteLabel = (value: number | null) => formatHostBytes(value, locale);
  const shareLabel = (value: number | null) => formatHostMetric(value, "share", locale);
  const tRef = useRef(t);
  tRef.current = t;
  const [reading, setReading] = useState<HostRead | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const active = useRef<{ span: HostSpan; busy: boolean } | null>(null);

  function request(nextSpan: HostSpan) {
    if (active.current?.busy && active.current.span === nextSpan) return;
    generation.current += 1;
    active.current = { span: nextSpan, busy: true };
    query.setFilter("span", nextSpan);
    setPhase("loading");
    setAttempt((value) => value + 1);
  }

  useEffect(() => {
    const id = ++generation.current;
    active.current = { span, busy: true };
    setPhase("loading");
    readHost(span)
      .then((body) => {
        if (generation.current !== id) return;
        active.current = { span, busy: false };
        setReading(body);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (generation.current !== id) return;
        active.current = { span, busy: false };
        if (isSessionExpiredError(error)) return;
        setPhase("failed");
        presentProblemNotification(tRef.current, error, {
          onRetry: () => {
            if (generation.current === id) request(span);
          },
        });
      });
    return () => {
      generation.current += 1;
      active.current = null;
    };
  }, [span, attempt]);

  const tabs = PANELS.map((value) => ({
        value,
        label: t(`host.panel.${value}`),
        panel: reading ? <div className={classes.page} aria-busy={phase === "loading"}>
          {value === "overview" ? <>
            <section aria-label={t("host.overview")} className={classes.overview}>
              <div className={classes.overviewGroup}>
                <div><Text size="sm" c="dimmed">{t("host.cpu.busy")}</Text><Text className={classes.primary}>{shareLabel(reading.tiles.cpu.busy_share)}</Text></div>
                <div className={classes.secondary}><Text size="sm">{t("host.cpu.online")}</Text><Text size="sm" fw={500}>{countLabel(reading.tiles.cpu.online_count)}</Text></div>
              </div>
              {(["memory", "swap"] as const).map((family) => <div key={family} className={classes.overviewGroup}>
                <div><Text size="sm" c="dimmed">{t(`host.${family}.used`)}</Text><Text className={classes.primary}>{byteLabel(reading.tiles[family].used_bytes)}</Text></div>
                <div className={classes.secondary}><Text size="sm">{t(`host.${family}.total`)}</Text><Text size="sm" fw={500}>{byteLabel(reading.tiles[family].total_bytes)}</Text></div>
                {family === "swap" && reading.tiles.swap.total_bytes === 0 ? <Text size="xs" c="dimmed">{t("host.swap.none")}</Text> : null}
              </div>)}
              <div className={classes.overviewGroup}>
                <div><Text size="sm" c="dimmed">{t("host.overview.postgres")}</Text><Text className={classes.primary}>{countLabel(reading.tiles.postgres.backends)}</Text></div>
                <div className={classes.secondary}><Text size="sm">{t("host.postgres.maxConnections")}</Text><Text size="sm" fw={500}>{countLabel(reading.tiles.postgres.max_connections)}</Text></div>
              </div>
            </section>
            <Text size="sm" c="dimmed">{t("host.observationHelp")}</Text>
            <section aria-labelledby="host-machine" className={classes.section}>
              <SectionHeader titleId="host-machine" title={t("host.section.machine")} order={4} />
              {reading.charts.run_queue.some((sample) => sample.v !== null) || Object.values(reading.charts.pressure).some((row) => [...row.waiting, ...row.stalled].some((sample) => sample.v !== null)) ? <div className={classes.chartGrid}>
                <HostChart title={t("host.cpu.runQueue")} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit="number" series={[{ name: t("host.cpu.runQueue"), samples: reading.charts.run_queue }]} />
                {(["cpu", "memory", "io"] as const).map((family) => <HostChart key={family} title={t(`host.pressure.${family}`)} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit="share" series={[
                  { name: t("host.pressure.waiting"), samples: reading.charts.pressure[family].waiting },
                  { name: t("host.pressure.stalled"), samples: reading.charts.pressure[family].stalled },
                ]} />)}
              </div> : <Text c="dimmed" size="sm">{t("host.empty.machine")}</Text>}
              <Disclosure title={t("host.advanced.cpu")}>
                {reading.charts.cpu_modes.some((mode) => mode.samples.some((sample) => sample.v !== null)) ? <HostChart title={t("host.cpu.modes")} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit="cpu-rate" series={reading.charts.cpu_modes.map((mode) => ({ name: mode.mode, samples: mode.samples }))} /> : <Text size="sm" c="dimmed">{t("host.chart.noSamples")}</Text>}
              </Disclosure>
            </section>
          </> : value === "storage" ? <Storage reading={reading} /> : value === "postgres" ? <Postgres reading={reading} /> : <Services reading={reading} />}
        </div> : null,
      }));
  return <PageTabs tabs={tabs} value={panel} onChange={(value) => query.setFilter("tab", value)}>{({ list, panels }) => (
    <PageChrome title={t("host.title")} description={t("host.purpose")}
      status={reading ? "ready" : phase === "failed" ? "unloaded" : "loading"} onRetry={() => request(span)}
      actions={<HeaderActions navigation={<HeaderAction><Button type="button" size="sm" variant="default"
        data-disabled={phase === "loading" || undefined} aria-disabled={phase === "loading"} aria-busy={phase === "loading"} onClick={() => request(span)}>{t("host.refresh")}</Button></HeaderAction>} />}
      toolbar={<div className={classes.controls}>
        <Group gap="sm" align="end" wrap="wrap">
          <NativeSelect label={t("host.span.label")} value={span} onChange={(event) => request(event.currentTarget.value as HostSpan)} data={["hour", "day", "retained"].map((value) => ({ value, label: t(`host.span.${value}`) }))} />
          <Text size="sm" c="dimmed" role="status" aria-live="polite" aria-atomic="true">{t(phase === "loading" ? "host.loading" : phase === "failed" ? "host.failed" : "host.loaded", { span: t(`host.span.${span}`) })}</Text>
        </Group>
        {reading ? <Group gap="xs" wrap="wrap">
          <Text size="sm">{t("host.displayedSpan", { span: t(`host.span.${reading.span}`) })}</Text>
          <Text size="sm" c="dimmed">{t("host.snapshot")}: <time dateTime={reading.end}>{showInstant(reading.end)}</time> · {zone}</Text>
          <Text size="sm" c="dimmed">{t("host.service.step", { seconds: reading.step_seconds })}</Text>
          {phase !== "ready" ? <Text size="sm" c="dimmed">{t("host.stale")}</Text> : null}
          {phase === "failed" ? <Button type="button" size="compact-sm" variant="subtle" onClick={() => request(span)}>{t("common.retry")}</Button> : null}
        </Group> : null}
        {span === "retained" ? <Text size="xs" c="dimmed">{t("host.retentionHelp")}</Text> : null}
      </div>} tabs={list}>{panels}</PageChrome>
  )}</PageTabs>;
}

function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details className={classes.disclosure} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary onClick={(event) => { event.preventDefault(); setOpen(!open); }}>{title}</summary>
    {open ? children : null}
  </details>;
}

function Storage({ reading }: { reading: HostRead }) {
  const t = useTranslate();
  const locale = useGetLocale()() ?? "en-US";
  const [selected, setSelected] = useState<string | null>(null);
  const mounts = [
    ...reading.tiles.filesystems.map((tile) => ({ mount: tile.mount, type: tile.type, tile, history: reading.charts.filesystems.find((row) => row.mount === tile.mount && row.type === tile.type) })),
    ...reading.charts.filesystems.filter((row) => !reading.tiles.filesystems.some((tile) => tile.mount === row.mount && tile.type === row.type)).map((history) => ({ mount: history.mount, type: history.type, tile: null, history })),
  ];
  const options = [
    ...mounts.map((row) => ({ value: JSON.stringify(["mount", row.mount, row.type]), label: `${row.mount} (${row.type})` })),
    ...reading.charts.disks.map((row) => ({ value: JSON.stringify(["disk", row.device]), label: `${t("host.disk.device")}: ${row.device}` })),
  ];
  const choice = options.some((row) => row.value === selected) ? selected : options[0]?.value;
  const mount = mounts.find((row) => JSON.stringify(["mount", row.mount, row.type]) === choice);
  const disk = reading.charts.disks.find((row) => JSON.stringify(["disk", row.device]) === choice);
  return <section aria-labelledby="host-storage" className={classes.section}>
    <SectionHeader titleId="host-storage" title={t("host.section.storage")} description={t("host.storageHelp")} order={4} />
    {options.length ? <>
      <div className={classes.inventory}>{mounts.map((row) => <div key={JSON.stringify([row.mount, row.type])} className={classes.inventoryRow}>
        <Text size="sm" fw={600} className={classes.identity}>{row.mount} <Text component="span" c="dimmed" size="sm">({row.type})</Text></Text>
        <Text size="sm">{t("host.filesystem.used")}: {formatHostBytes(row.tile?.used_bytes ?? null, locale)} / {formatHostBytes(row.tile?.total_bytes ?? null, locale)}</Text>
        <Text size="sm" c="dimmed">{t("host.filesystem.share")}: {formatHostMetric(row.tile?.used_share ?? null, "share", locale)} · {t("host.filesystem.freeInodes")}: {formatHostNumber(row.tile?.free_inodes ?? null, locale)}</Text>
      </div>)}</div>
      <NativeSelect label={t("host.storage.select")} value={choice ?? ""} onChange={(event) => setSelected(event.currentTarget.value)} data={options} />
      {mount ? <div className={classes.resource}>
        <Title order={5} className={classes.identity}>{mount.mount} ({mount.type})</Title>
        {mount.history ? <div className={classes.chartGrid}>{(["available", "delta"] as const).map((field) => <HostChart key={field} title={t(`host.filesystem.${field}`)} label={`${mount.mount} (${mount.type}) · ${t(`host.filesystem.${field}`)}`} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit={field === "available" ? "bytes" : "byte-change"} series={[{ name: t(`host.filesystem.${field}`), samples: mount.history![field] }]} />)}</div> : <Text size="sm" c="dimmed">{t("host.chart.noSamples")}</Text>}
      </div> : null}
      {disk ? <div className={classes.resource}>
        <Title order={5} className={classes.identity}>{t("host.disk.device")}: {disk.device}</Title>
        <div className={classes.chartGrid}>{(["busy_share", "queue_length"] as const).map((field) => {
          const title = t(field === "busy_share" ? "host.disk.busy" : "host.disk.queue");
          return <HostChart key={field} title={title} label={`${disk.device} · ${title}`} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit={field === "busy_share" ? "share" : "number"} series={[{ name: title, samples: disk[field] }]} />;
        })}</div>
      </div> : null}
    </> : <Text size="sm" c="dimmed">{t("host.empty.storage")}</Text>}
  </section>;
}

function Postgres({ reading }: { reading: HostRead }) {
  const t = useTranslate();
  const charts = (items: typeof POSTGRES_CHARTS) => <div className={classes.chartGrid}>{items.map((chart) => <HostChart key={chart.field} title={t(chart.key)} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit={chart.field === "temp_bytes" ? "bytes" : "number"} series={[{ name: t(chart.key), samples: reading.charts.postgres[chart.field] }]} />)}</div>;
  return <section aria-labelledby="host-postgres" className={classes.section}>
    <SectionHeader titleId="host-postgres" title={t("host.section.postgres")} description={t("host.postgres.counterHelp")} order={4} />
    {POSTGRES_CHARTS.slice(0, 3).some((chart) => reading.charts.postgres[chart.field].some((sample) => sample.v !== null)) ? charts(POSTGRES_CHARTS.slice(0, 3)) : <Text size="sm" c="dimmed">{t("host.empty.postgres")}</Text>}
    <Disclosure title={t("host.advanced.checkpoints")}>{POSTGRES_CHARTS.slice(3, 8).some((chart) => reading.charts.postgres[chart.field].some((sample) => sample.v !== null)) ? charts(POSTGRES_CHARTS.slice(3, 8)) : <Text size="sm" c="dimmed">{t("host.chart.noSamples")}</Text>}</Disclosure>
    <Disclosure title={t("host.advanced.temp")}>{POSTGRES_CHARTS.slice(8).some((chart) => reading.charts.postgres[chart.field].some((sample) => sample.v !== null)) ? charts(POSTGRES_CHARTS.slice(8)) : <Text size="sm" c="dimmed">{t("host.chart.noSamples")}</Text>}</Disclosure>
  </section>;
}

function Services({ reading }: { reading: HostRead }) {
  const t = useTranslate();
  const locale = useGetLocale()() ?? "en-US";
  const showInstant = useShowInstant();
  const [selected, setSelected] = useState<string[]>(["api", "worker"]);
  const compared = reading.charts.services.filter((service) => selected.includes(service.service));
  return <section aria-labelledby="host-services" className={classes.section}>
    <SectionHeader titleId="host-services" title={t("host.section.services")} description={t("host.servicesHelp")} order={4} />
    <fieldset className={classes.servicePicker}><legend>{t("host.service.compare")}</legend>
      {reading.charts.services.map((service) => <div key={service.service} data-service={service.service} className={classes.serviceChoice}>
        <Checkbox label={service.service} checked={selected.includes(service.service)} onChange={(event) => setSelected(event.currentTarget.checked ? [...selected, service.service] : selected.filter((name) => name !== service.service))} />
        {(["cpu_seconds", "memory_bytes"] as const).map((field) => {
          const latest = [...service[field]].reverse().find((sample) => sample.v !== null);
          return <div key={field}>
            <Text size="xs" c="dimmed">{t(field === "cpu_seconds" ? "host.service.cpu" : "host.service.memory")}</Text>
            <Text size="sm">{formatHostMetric(latest?.v ?? null, field === "cpu_seconds" ? "cpu-step" : "bytes", locale)}</Text>
            {latest ? <Text size="xs" c="dimmed">{t("host.chart.lastObserved")}: <time dateTime={latest.t}>{showInstant(latest.t)}</time></Text> : <Text size="xs" c="dimmed">{t("host.chart.noSamples")}</Text>}
          </div>;
        })}
      </div>)}
    </fieldset>
    {compared.length && compared.some((service) => [...service.cpu_seconds, ...service.memory_bytes].some((sample) => sample.v !== null)) ? <div className={classes.chartGrid}>{(["cpu_seconds", "memory_bytes"] as const).map((field) => <HostChart key={field} title={t(field === "cpu_seconds" ? "host.service.cpu" : "host.service.memory")} start={reading.start} end={reading.end} stepSeconds={reading.step_seconds} unit={field === "cpu_seconds" ? "cpu-step" : "bytes"} series={compared.map((service) => ({ name: service.service, samples: service[field] }))} />)}</div> : <Text size="sm" c="dimmed">{t(compared.length ? "host.chart.noSamples" : "host.service.selectHelp")}</Text>}
  </section>;
}
