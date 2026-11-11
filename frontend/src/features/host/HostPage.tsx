"use client";

import { Group, SegmentedControl, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { PageChrome } from "@/components/layout/PageChrome";
import { readHost } from "@/features/host/api";
import { HostChart } from "@/features/host/HostChart";
import type { HostRead, HostSpan, PostgresChart } from "@/features/host/types";
import { isSessionExpiredError } from "@/lib/api";

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
  const tRef = useRef(t);
  tRef.current = t;
  const [span, setSpan] = useState<HostSpan>("day");
  const [reading, setReading] = useState<HostRead | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setReading(null);
    readHost(span)
      .then((body) => {
        if (cancelled) return;
        setReading(body);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (isSessionExpiredError(error)) return;
        setReading(null);
        setPhase("failed");
        presentProblemNotification(tRef.current, error);
      });
    return () => {
      cancelled = true;
    };
  }, [span]);

  return (
    <PageChrome
      title={t("host.title")}
      status={phase === "loading" ? "loading" : "ready"}
      toolbar={
        <SegmentedControl
          value={span}
          onChange={(value) => setSpan(value as HostSpan)}
          data={[
            { label: t("host.span.hour"), value: "hour" },
            { label: t("host.span.day"), value: "day" },
            { label: t("host.span.retained"), value: "retained" },
          ]}
        />
      }
    >
      {phase === "ready" && reading ? (
        <Stack gap="lg">
          <Group>
            <Stack gap={0}>
              <Text size="sm">{t("host.cpu.online")}</Text>
              <Text>{countLabel(reading.tiles.cpu.online_count)}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="sm">{t("host.cpu.busy")}</Text>
              <Text>{shareLabel(reading.tiles.cpu.busy_share)}</Text>
            </Stack>
          </Group>
          <HostChart
            title={t("host.cpu.modes")}
            start={reading.start}
            end={reading.end}
            nowLabel={t("host.axis.now")}
            series={reading.charts.cpu_modes.map((mode) => ({
              name: mode.mode,
              samples: mode.samples,
            }))}
          />
          <HostChart
            title={t("host.cpu.runQueue")}
            start={reading.start}
            end={reading.end}
            nowLabel={t("host.axis.now")}
            series={[
              { name: t("host.cpu.runQueue"), samples: reading.charts.run_queue },
            ]}
          />
          <Group>
            <Stack gap={0}>
              <Text size="sm">{t("host.memory.used")}</Text>
              <Text>{countLabel(reading.tiles.memory.used_bytes)}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="sm">{t("host.memory.total")}</Text>
              <Text>{countLabel(reading.tiles.memory.total_bytes)}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="sm">{t("host.swap.used")}</Text>
              <Text>{countLabel(reading.tiles.swap.used_bytes)}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="sm">{t("host.swap.total")}</Text>
              <Text>{countLabel(reading.tiles.swap.total_bytes)}</Text>
            </Stack>
          </Group>
          {reading.tiles.filesystems.map((row) => {
            const history = reading.charts.filesystems.find(
              (chart) => chart.mount === row.mount && chart.type === row.type,
            );
            return (
              <Stack key={`${row.mount}-${row.type}`} gap="xs">
                <Group>
                  <Stack gap={0}>
                    <Text size="sm">{t("host.filesystem.mount")}</Text>
                    <Text>{row.mount}</Text>
                  </Stack>
                  <Stack gap={0}>
                    <Text size="sm">{t("host.filesystem.type")}</Text>
                    <Text>{row.type}</Text>
                  </Stack>
                  <Stack gap={0}>
                    <Text size="sm">{t("host.filesystem.used")}</Text>
                    <Text>{countLabel(row.used_bytes)}</Text>
                  </Stack>
                  <Stack gap={0}>
                    <Text size="sm">{t("host.filesystem.total")}</Text>
                    <Text>{countLabel(row.total_bytes)}</Text>
                  </Stack>
                  <Stack gap={0}>
                    <Text size="sm">{t("host.filesystem.share")}</Text>
                    <Text>{shareLabel(row.used_share)}</Text>
                  </Stack>
                  <Stack gap={0}>
                    <Text size="sm">{t("host.filesystem.freeInodes")}</Text>
                    <Text>{countLabel(row.free_inodes)}</Text>
                  </Stack>
                </Group>
                {history ? (
                  <HostChart
                    title={t("host.filesystem.available")}
                    label={row.mount}
                    start={reading.start}
                    end={reading.end}
                    nowLabel={t("host.axis.now")}
                    series={[
                      { name: t("host.filesystem.available"), samples: history.available },
                      { name: t("host.filesystem.delta"), samples: history.delta },
                    ]}
                  />
                ) : null}
              </Stack>
            );
          })}
          {reading.charts.filesystems
            .filter(
              (chart) =>
                !reading.tiles.filesystems.some(
                  (row) => row.mount === chart.mount && row.type === chart.type,
                ),
            )
            .map((chart) => (
              <HostChart
                key={`${chart.mount}-${chart.type}`}
                title={chart.mount}
                start={reading.start}
                end={reading.end}
                nowLabel={t("host.axis.now")}
                series={[
                  { name: t("host.filesystem.available"), samples: chart.available },
                  { name: t("host.filesystem.delta"), samples: chart.delta },
                ]}
              />
            ))}
          {reading.charts.disks.map((disk) => (
            <Stack key={disk.device} gap="xs">
              <Text size="sm">{t("host.disk.device")}</Text>
              <HostChart
                title={disk.device}
                start={reading.start}
                end={reading.end}
                nowLabel={t("host.axis.now")}
                series={[
                  { name: t("host.disk.busy"), samples: disk.busy_share },
                  { name: t("host.disk.queue"), samples: disk.queue_length },
                ]}
              />
            </Stack>
          ))}
          {(["cpu", "memory", "io"] as const).map((family) => (
            <HostChart
              key={family}
              title={t(`host.pressure.${family}`)}
              start={reading.start}
              end={reading.end}
              nowLabel={t("host.axis.now")}
              series={[
                {
                  name: t("host.pressure.waiting"),
                  samples: reading.charts.pressure[family].waiting,
                },
                {
                  name: t("host.pressure.stalled"),
                  samples: reading.charts.pressure[family].stalled,
                },
              ]}
            />
          ))}
          <Group>
            <Stack gap={0}>
              <Text size="sm">{t("host.postgres.backends")}</Text>
              <Text>{countLabel(reading.tiles.postgres.backends)}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="sm">{t("host.postgres.maxConnections")}</Text>
              <Text>{countLabel(reading.tiles.postgres.max_connections)}</Text>
            </Stack>
          </Group>
          {POSTGRES_CHARTS.map((chart) => {
            const title = t(chart.key);
            return (
              <HostChart
                key={chart.field}
                title={title}
                start={reading.start}
                end={reading.end}
                nowLabel={t("host.axis.now")}
                series={[{ name: title, samples: reading.charts.postgres[chart.field] }]}
              />
            );
          })}
          {reading.charts.services.map((service) => (
            <HostChart
              key={service.service}
              title={service.service}
              start={reading.start}
              end={reading.end}
              nowLabel={t("host.axis.now")}
              series={[
                { name: t("host.service.cpu"), samples: service.cpu_seconds },
                { name: t("host.service.memory"), samples: service.memory_bytes },
              ]}
            />
          ))}
        </Stack>
      ) : null}
    </PageChrome>
  );
}

function countLabel(value: number | null): string {
  if (value == null) return "—";
  return String(value);
}

function shareLabel(value: number | null): string {
  if (value == null) return "—";
  const percent = Math.round(value * 1000) / 10;
  return `${percent}%`;
}
