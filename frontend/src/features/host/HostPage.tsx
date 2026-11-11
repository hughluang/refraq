"use client";

import { Group, SegmentedControl, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { PageChrome } from "@/components/layout/PageChrome";
import { readHost } from "@/features/host/api";
import { HostChart } from "@/features/host/HostChart";
import type { HostRead, HostSpan } from "@/features/host/types";
import { isSessionExpiredError } from "@/lib/api";

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
