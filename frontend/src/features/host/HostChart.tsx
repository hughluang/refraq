"use client";

import { Group, Stack, Text } from "@mantine/core";

import type { HostSample } from "@/features/host/types";

const STROKES = [
  "var(--mantine-color-blue-6)",
  "var(--mantine-color-orange-6)",
  "var(--mantine-color-teal-6)",
  "var(--mantine-color-grape-6)",
  "var(--mantine-color-red-6)",
  "var(--mantine-color-cyan-6)",
  "var(--mantine-color-yellow-7)",
  "var(--mantine-color-gray-7)",
];

type ChartSeries = {
  name: string;
  samples: HostSample[];
};

export function HostChart({
  title,
  start,
  end,
  nowLabel,
  series,
}: {
  title: string;
  start: string;
  end: string;
  nowLabel: string;
  series: ChartSeries[];
}) {
  const ticks = axisTicks(start, end, nowLabel);
  return (
    <Stack gap="xs">
      <Text fw={600}>{title}</Text>
      {series.map((item) => {
        const latest = latestValue(item.samples);
        return (
          <Group key={item.name} gap="xs">
            {item.name !== title ? <Text size="sm">{item.name}</Text> : null}
            {latest != null ? <Text size="sm">{latest}</Text> : null}
          </Group>
        );
      })}
      <svg role="img" aria-label={title} viewBox="0 0 720 160" width="100%" height="160">
        {series.map((item, index) =>
          polylines(item.samples).map((points, run) => (
            <polyline
              key={`${item.name}-${run}`}
              fill="none"
              stroke={STROKES[index % STROKES.length]}
              strokeWidth="2"
              points={points}
            />
          )),
        )}
      </svg>
      <Group justify="space-between">
        {ticks.map((label, index) => (
          <Text key={`${label}-${index}`} size="xs">
            {label}
          </Text>
        ))}
      </Group>
    </Stack>
  );
}

function latestValue(samples: HostSample[]): string | null {
  for (let index = samples.length - 1; index >= 0; index -= 1) {
    const value = samples[index]?.v;
    if (value != null) return String(value);
  }
  return null;
}

function axisTicks(start: string, end: string, nowLabel: string): string[] {
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  const marks = [startMs, Math.round((startMs + endMs) / 2), endMs];
  const unique: number[] = [];
  for (const mark of marks) {
    if (unique.length === 0 || unique[unique.length - 1] !== mark) unique.push(mark);
  }
  return unique.map((mark) => offsetLabel(endMs, mark, nowLabel));
}

function offsetLabel(endMs: number, markMs: number, nowLabel: string): string {
  const delta = Math.round((endMs - markMs) / 1000);
  if (delta === 0) return nowLabel;
  const past = Math.abs(delta);
  if (past % 3600 === 0) return `-${past / 3600}h`;
  if (past % 60 === 0) return `-${past / 60}m`;
  return `-${past}s`;
}

function polylines(samples: HostSample[]): string[] {
  const numbers = samples.flatMap((sample) => (sample.v != null ? [sample.v] : []));
  if (numbers.length === 0) return [];
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  const span = max - min || 1;
  const yOf = (value: number) => 150 - ((value - min) / span) * 140;
  const xOf = (index: number) =>
    samples.length === 1 ? 0 : (index / (samples.length - 1)) * 720;
  const runs: string[] = [];
  let current: string[] = [];
  samples.forEach((sample, index) => {
    if (sample.v == null) {
      if (current.length > 0) {
        runs.push(joinRun(current));
        current = [];
      }
      return;
    }
    current.push(`${xOf(index).toFixed(2)},${yOf(sample.v).toFixed(2)}`);
  });
  if (current.length > 0) runs.push(joinRun(current));
  return runs;
}

function joinRun(points: string[]): string {
  if (points.length === 1) return `${points[0]} ${points[0]}`;
  return points.join(" ");
}
