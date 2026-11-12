"use client";

import { Group, Stack, Text } from "@mantine/core";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { useEffect, useId, useRef, useState } from "react";

import { formatHostMetric, type HostMetricUnit } from "@/features/host/format";
import type { HostSample } from "@/features/host/types";
import { Instant } from "@/lib/instant";
import { useShowInstant } from "@/hooks/useFormatInstant";
import classes from "./HostChart.module.css";

const STROKES = [
  "var(--mantine-color-blue-6)", "var(--mantine-color-orange-6)",
  "var(--mantine-color-teal-6)", "var(--mantine-color-grape-6)",
  "var(--mantine-color-red-6)", "var(--mantine-color-cyan-6)",
  "var(--mantine-color-yellow-7)", "var(--mantine-color-gray-7)",
];
const DASHES = [undefined, "8 4", "2 4", "8 3 2 3"];
type ChartSeries = { name: string; samples: HostSample[] };

// Each plot owns one unit/meaning. Bounds are response bounds, not series bounds.
// Adjacent observations more than 1.5 evaluation steps apart form separate runs.
export function HostChart({ title, label, start, end, stepSeconds, unit, series }: {
  title: string;
  label?: string;
  start: string;
  end: string;
  stepSeconds: number;
  unit: HostMetricUnit;
  series: ChartSeries[];
}) {
  const t = useTranslate();
  const locale = useGetLocale()() ?? "en-US";
  const showInstant = useShowInstant();
  const id = useId();
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [tickWidth, setTickWidth] = useState(0);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [pointerTime, setPointerTime] = useState<string | null>(null);
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries.find((item) => item.target === node);
      if (entry && entry.contentRect.width > 0) setWidth(entry.contentRect.width);
      setTickWidth(Math.max(0, ...Array.from(node.querySelectorAll<SVGTextElement>("svg text"), (label) => label.getBBox().width)));
    });
    observer.observe(node);
    node.querySelectorAll("svg text").forEach((label) => observer.observe(label));
    return () => observer.disconnect();
  }, []);
  const startMs = Instant.epochMsOf(start) ?? NaN;
  const endMs = Instant.epochMsOf(end) ?? NaN;
  const validBounds = Number.isFinite(startMs) && Number.isFinite(endMs);
  const ordered = series.map((item) => ({ ...item, samples: [...item.samples].sort((a, b) => (Instant.epochMsOf(a.t) ?? Infinity) - (Instant.epochMsOf(b.t) ?? Infinity)) }));
  const values = ordered.flatMap((item) => item.samples.flatMap((sample) => sample.v === null || Instant.epochMsOf(sample.t) === null ? [] : [sample.v]));
  const min = Math.min(0, ...values);
  const max = Math.max(unit === "share" ? 1 : 0, ...values);
  const low = min === max && unit === "byte-change" ? -1 : min;
  const high = min === max ? 1 : max;
  const ticks = [high, low < 0 && high > 0 ? 0 : (high + low) / 2, low];
  const valueText = (value: number | null) => formatHostMetric(value, unit, locale);
  const left = Math.max(44, tickWidth + 12, ...ticks.map((value) => valueText(value).length * 7.5 + 12));
  const right = Math.max(left + 1, width - 12);
  const x = (time: string) => left + (endMs === startMs ? 0.5 : (Date.parse(time) - startMs) / (endMs - startMs)) * (right - left);
  const y = (value: number) => 176 - (value - low) / (high - low) * 160;
  const times = [...new Set(ordered.flatMap((item) => item.samples.map((sample) => sample.t)))].sort((a, b) => Date.parse(a) - Date.parse(b));
  const current = Math.max(0, times.indexOf(selected ?? ""));
  const sampleTime = times[current];
  const inspectedTime = pointerTime && times.includes(pointerTime) ? pointerTime : null;
  const cursorTime = inspectedTime ?? (open ? sampleTime : null);
  const offset = (mark: number) => {
    if (!validBounds) return t("problems.API_CONTRACT_INVALID");
    const seconds = Math.round((endMs - mark) / 1000);
    if (seconds === 0) return t("host.snapshot");
    const divisor = seconds % 3600 === 0 ? 3600 : seconds % 60 === 0 ? 60 : 1;
    const key = divisor === 3600 ? "hoursAgo" : divisor === 60 ? "minutesAgo" : "secondsAgo";
    return t(`host.axis.${key}`, { count: new Intl.NumberFormat(locale).format(seconds / divisor) });
  };
  return (
    <Stack gap="xs" className={classes.chart} ref={container}>
      <Text fw={600}>{title}</Text>
      {ordered.map((item, index) => {
        const latest = item.samples.findLast((sample) => sample.v !== null);
        return (
          <Group key={item.name} gap="xs" className={classes.legend}>
            <svg width="28" height="14" aria-hidden="true">
              <line x1="0" x2="28" y1="7" y2="7" stroke={STROKES[index % STROKES.length]} strokeWidth="2" strokeDasharray={DASHES[index % DASHES.length]} />
              <circle cx="14" cy="7" r={3.5 + index % 3} fill={index % 2 ? "var(--mantine-color-body)" : STROKES[index % STROKES.length]} stroke={STROKES[index % STROKES.length]} strokeWidth="2" />
            </svg>
            <Text size="sm"><span aria-hidden="true">{index + 1}. </span><span>{item.name}</span></Text>
            {latest ? <Text size="sm"><span>{valueText(latest.v)}</span> · {t("host.chart.lastObserved")}: <time dateTime={latest.t}>{showInstant(latest.t)}</time></Text> : <Text size="sm" c="dimmed">{t("host.chart.noSamples")}</Text>}
          </Group>
        );
      })}
      {values.length === 0 ? <Text size="sm" c="dimmed">{t("host.chart.noSamples")}</Text> : null}
      <div className={classes.plotArea} onPointerLeave={() => setPointerTime(null)}>
      <svg className={classes.plot} role="img" aria-label={label ?? title} aria-describedby={`${id}-description`} width="100%" height="188"
        onPointerMove={(event) => {
          if (!times.length || !validBounds) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          const target = event.clientX - bounds.left;
          let nearest = 0;
          times.forEach((time, index) => { if (Math.abs(x(time) - target) < Math.abs(x(times[nearest]!) - target)) nearest = index; });
          setPointerTime(times[nearest]!);
        }}>
        <title>{label ?? title}</title>
        <desc id={`${id}-description`}>{t("host.chart.samples")}. {t("host.chart.lastObserved")}. {series.map((item) => item.name).join(", ")}</desc>
        {ticks.map((value, index) => <g key={index}>
          <line x1={left} x2={right} y1={y(value)} y2={y(value)} className={classes.grid} />
          <text x={left - 8} y={y(value)} textAnchor="end" dominantBaseline="middle">{valueText(value)}</text>
        </g>)}
        {ordered.map((item, index) => (validBounds ? runs(item.samples, stepSeconds) : []).map((run, runIndex) => {
          const color = STROKES[index % STROKES.length];
          return run.length === 1 ? <circle key={`${index}-${runIndex}`} data-series={item.name} cx={x(run[0]!.t)} cy={y(run[0]!.v!)} r={3.5 + index % 3} fill={index % 2 ? "var(--mantine-color-body)" : color} stroke={color} strokeWidth="2" /> :
            <polyline key={`${index}-${runIndex}`} data-series={item.name} fill="none" stroke={color} strokeWidth="2" strokeDasharray={DASHES[index % DASHES.length]} points={run.map((point) => `${x(point.t).toFixed(2)},${y(point.v!).toFixed(2)}`).join(" ")} />;
        }))}
        {cursorTime && validBounds && Instant.epochMsOf(cursorTime) !== null ? <line x1={x(cursorTime)} x2={x(cursorTime)} y1="16" y2="176" className={classes.cursor} /> : null}
      </svg>
      {inspectedTime ? <div className={classes.pointerReadout} aria-hidden="true">
        <time dateTime={inspectedTime}>{showInstant(inspectedTime)}</time>
        {ordered.map((item, index) => <div key={item.name}>{index + 1}. {item.name}: {valueText(item.samples.find((sample) => sample.t === inspectedTime)?.v ?? null)}</div>)}
      </div> : null}
      </div>
      <div className={classes.timeAxis} data-axis="time" style={{ paddingInlineStart: left, paddingInlineEnd: width - right, gridTemplateColumns: width >= 500 ? "repeat(3, minmax(0, 1fr))" : "minmax(0, 1fr)" }}>
        <span>{offset(startMs)}</span>
        {width >= 500 ? <span>{offset((startMs + endMs) / 2)}</span> : null}
        <span>{offset(endMs)}</span>
      </div>
      {times.length ? <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary onClick={(event) => { event.preventDefault(); setOpen(!open); }}>{t("host.chart.samples")}</summary>
        {open && sampleTime ? <Stack gap="xs">
          <label htmlFor={`${id}-sample`}>{t("host.chart.time")}</label>
          <input id={`${id}-sample`} type="range" min={0} max={times.length - 1} step={1} value={current}
            aria-valuetext={showInstant(sampleTime)}
            onChange={(event) => setSelected(times[Number(event.currentTarget.value)]!)}
            onKeyDown={(event) => {
              const next = event.key === "Home" ? 0 : event.key === "End" ? times.length - 1 : event.key === "ArrowRight" || event.key === "ArrowUp" ? Math.min(current + 1, times.length - 1) : event.key === "ArrowLeft" || event.key === "ArrowDown" ? Math.max(current - 1, 0) : null;
              if (next !== null) { event.preventDefault(); setSelected(times[next]!); }
            }} />
          <time dateTime={sampleTime}>{showInstant(sampleTime)}</time>
          <dl className={classes.readout}>{ordered.map((item, index) => <div key={item.name}>
            <dt>{index + 1}. {item.name}</dt>
            <dd>{t("host.chart.value")}: {valueText(item.samples.find((sample) => sample.t === sampleTime)?.v ?? null)}</dd>
          </div>)}</dl>
        </Stack> : null}
      </details> : null}
    </Stack>
  );
}

function runs(samples: HostSample[], stepSeconds: number): HostSample[][] {
  const result: HostSample[][] = [];
  let run: HostSample[] = [];
  for (const sample of samples) {
    const previous = run.at(-1);
    if (sample.v === null || Instant.epochMsOf(sample.t) === null || (previous && Date.parse(sample.t) - Date.parse(previous.t) > stepSeconds * 1500)) {
      if (run.length) result.push(run);
      run = [];
    }
    if (sample.v !== null && Instant.epochMsOf(sample.t) !== null) run.push(sample);
  }
  if (run.length) result.push(run);
  return result;
}
