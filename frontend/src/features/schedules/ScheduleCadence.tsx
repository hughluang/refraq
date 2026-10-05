"use client";

import { Text, Tooltip } from "@mantine/core";
import { useGetLocale, useTranslate } from "@refinedev/core";

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
    return <Text size="sm">{`${task.interval_seconds}s`}</Text>;
  }
  if (!task.cron) return <Text size="sm">—</Text>;

  const friendly = describeCron(task.cron, locale, cronTimezone, t);
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
          {task.cron}
        </Text>
      }
    >
      <Text size="sm">{friendly}</Text>
    </Tooltip>
  );
}
