"use client";

import { Group, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useId, useState } from "react";
import type { FleetThroughput, ThroughputPoint, ThroughputRate } from "./fleetTypes";
import { utcSample } from "./fleetFormat";
import classes from "./Operations.module.css";

const series = ["received", "committed"] as const;
type Series = typeof series[number];

function rate(value: number | null) {
  return value == null ? "—" : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
}

export function throughputRuns(points: ThroughputPoint[], key: Series) {
  const runs: { point: ThroughputPoint; index: number }[][] = [];
  let current: { point: ThroughputPoint; index: number }[] = [];
  points.forEach((point, index) => {
    if (point[key].value == null) { if (current.length) runs.push(current); current = []; }
    else current.push({ point, index });
  });
  if (current.length) runs.push(current);
  return runs;
}

export function FleetThroughputChart({ data, hours, onHoursChange, stale = false }: {
  data: FleetThroughput | null; hours: string; onHoursChange: (value: string) => void; stale?: boolean;
}) {
  const t = useTranslate();
  const id = useId();
  const points = data?.points ?? [];
  const [selected, setSelected] = useState<number | null>(null);
  const active = Math.max(0, Math.min(selected ?? points.length - 1, points.length - 1));
  const sample = points[active];
  const max = Math.max(1, ...points.flatMap(point => series.map(key => point[key].value ?? 0)));
  const left = 58, right = 740, top = 16, bottom = 190;
  const x = (index: number) => left + index / Math.max(1, points.length - 1) * (right - left);
  const y = (value: number) => bottom - value / max * (bottom - top);
  function inspect(clientX: number, element: SVGSVGElement) {
    if (!points.length) return;
    const box = element.getBoundingClientRect();
    const location = (clientX - box.left) / box.width * 760;
    setSelected(Math.max(0, Math.min(points.length - 1, Math.round((location - left) / (right - left) * (points.length - 1)))));
  }
  const measured = points.some(point => series.some(key => point[key].value != null));
  return <section className={classes.section} aria-labelledby={`${id}-title`}>
    <Group justify="space-between" align="flex-start" gap="sm">
      <div><Title id={`${id}-title`} order={2} size="h4">{t("fleet.throughput")}</Title><Text size="sm" c="dimmed">{t("fleet.throughputHelp")}</Text></div>
      <SegmentedControl size="xs" aria-label={t("fleet.chartWindow")} value={hours} onChange={value => { setSelected(null); onHoursChange(value); }}
        data={["1", "6", "24"].map(value => ({ value, label: t("fleet.hours", { count: Number(value) }) }))} />
    </Group>
    {stale && <Text size="sm" role="status">{t("diagnostics.staleSnapshot")}</Text>}
    <Group gap="xl" mt="md" aria-label={t("fleet.chartSeries")}>
      {series.map((key, index) => <Group key={key} gap="xs"><svg width="28" height="12" aria-hidden="true"><line x1="0" x2="28" y1="6" y2="6" className={classes[key]} strokeDasharray={index ? "5 4" : undefined} strokeWidth="2" /></svg><Text size="sm">{t(`fleet.${key}`)}</Text></Group>)}
      <Text size="xs" c="dimmed">MB/s</Text>
    </Group>
    {data && !measured && <Text role="status" size="sm" my="sm">{t("fleet.noThroughput")}</Text>}
    <svg className={classes.chart} viewBox="0 0 760 218" role="img" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}
      onPointerMove={event => { if (event.pointerType !== "touch") inspect(event.clientX, event.currentTarget); }}
      onPointerDown={event => inspect(event.clientX, event.currentTarget)}>
      <desc id={`${id}-description`}>{t("fleet.chartDescription")}</desc>
      {[0, max / 2, max].map((value, index) => <g key={index}><line x1={left} x2={right} y1={y(value)} y2={y(value)} className={classes.chartGrid} /><text x={left - 10} y={y(value)} textAnchor="end" dominantBaseline="middle">{rate(value)}</text></g>)}
      {series.map((key, seriesIndex) => throughputRuns(points, key).map((run, index) => run.length === 1
        ? <circle key={`${key}-${index}`} data-series={key} cx={x(run[0].index)} cy={y(run[0].point[key].value!)} r="3" className={classes[key]} />
        : <polyline key={`${key}-${index}`} data-series={key} points={run.map(({ point, index }) => `${x(index)},${y(point[key].value!)}`).join(" ")}
          className={classes[key]} fill="none" strokeWidth="2" strokeDasharray={seriesIndex ? "5 4" : undefined} />))}
      {sample && <line x1={x(active)} x2={x(active)} y1={top} y2={bottom} className={classes.chartCursor} />}
      <text x={left} y="212">{data ? utcSample(data.window_start).slice(11, 16) : ""}</text>
      <text x={right} y="212" textAnchor="end">{data ? `${utcSample(data.window_end).slice(11, 16)} UTC` : ""}</text>
    </svg>
    {sample && <Stack gap="xs">
      <label htmlFor={`${id}-sample`}><Text span size="sm">{t("fleet.inspectSample")}: <time dateTime={sample.at}>{utcSample(sample.at)}</time></Text></label>
      <input className={classes.sampleSlider} id={`${id}-sample`} type="range" min={0} max={Math.max(0, points.length - 1)} step={1} value={active}
        aria-valuetext={`${utcSample(sample.at)}; ${t("fleet.received")}: ${sample.received.value == null ? t("diagnostics.unavailable") : rate(sample.received.value)} MB/s; ${t("fleet.committed")}: ${sample.committed.value == null ? t("diagnostics.unavailable") : rate(sample.committed.value)} MB/s`}
        onChange={event => setSelected(Number(event.currentTarget.value))}
        onKeyDown={event => {
          const next = event.key === "Home" ? 0 : event.key === "End" ? points.length - 1
            : event.key === "ArrowRight" || event.key === "ArrowUp" ? Math.min(points.length - 1, active + 1)
              : event.key === "ArrowLeft" || event.key === "ArrowDown" ? Math.max(0, active - 1) : null;
          if (next != null) { event.preventDefault(); setSelected(next); }
        }} />
      <div className={classes.rateReadouts} aria-live="polite" aria-atomic="true">
        {series.map(key => <RateReading key={key} label={t(`fleet.${key}`)} sample={sample[key]} total={data?.mirror_count ?? 0} />)}
      </div>
    </Stack>}
  </section>;
}

function RateReading({ label, sample, total }: { label: string; sample: ThroughputRate; total: number }) {
  const t = useTranslate();
  return <div>
    <Text size="sm" fw={500}>{label}: {sample.value == null ? t("diagnostics.unavailable") : `${rate(sample.value)} MB/s`}</Text>
    <Text size="xs" c="dimmed">{t("diagnostics.coverage", { sampled: sample.sampled, total, missing: sample.missing })}</Text>
    {sample.interval_start && <Text size="xs" c="dimmed">{utcSample(sample.interval_start)} — {utcSample(sample.interval_end)}</Text>}
  </div>;
}
