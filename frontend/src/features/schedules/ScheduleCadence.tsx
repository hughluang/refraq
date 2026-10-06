"use client";

import { Text, Tooltip } from "@mantine/core";
import { useGetLocale, useTranslate } from "@refinedev/core";

import { describeIntervalSeconds } from "@/features/schedules/cronCadence";
import { describeCron } from "@/features/schedules/cronDescription";
import type { ScheduledTask } from "@/features/schedules/types";

type Props = {
  task: ScheduledTask;
  cronTimezone: string | null;
};

/** Cadence as a friendly sentence; the raw cron expression sits in a tooltip. */
export function ScheduleCadence({ task, cronTimezone }: Props) {
  const t = useTranslate();
  const locale = useGetLocale()() ?? "en-US";

  if (task.interval_seconds) {
    return (
      <Text size="sm">{describeIntervalSeconds(task.interval_seconds, t)}</Text>
    );
  }
  if (!task.cron) return <Text size="sm">—</Text>;

  const friendly = describeCron(task.cron, locale, t);
  if (friendly === null) {
    return (
      <Text size="sm" ff="monospace">
        {task.cron}
      </Text>
    );
  }
  return (
    <Tooltip
      label={
        <Text size="xs" ff="monospace">
          {cronTimezone ? `${task.cron} (${cronTimezone})` : task.cron}
        </Text>
      }
    >
      <Text size="sm">{friendly}</Text>
    </Tooltip>
  );
}
