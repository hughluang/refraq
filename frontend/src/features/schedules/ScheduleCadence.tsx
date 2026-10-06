"use client";

import { Stack, Text, Tooltip } from "@mantine/core";
import { useGetLocale, useTranslate } from "@refinedev/core";

import { describeIntervalSeconds } from "@/features/schedules/cronCadence";
import { describeCron } from "@/features/schedules/cronDescription";
import { startsInFuture } from "@/features/schedules/startAtField";
import type { ScheduledTask } from "@/features/schedules/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";

type Props = {
  task: ScheduledTask;
  cronTimezone: string | null;
};

/** Cadence as a friendly sentence; the raw cron expression sits in a tooltip. */
export function ScheduleCadence({ task, cronTimezone }: Props) {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const startHint = startsInFuture(task.start_at) ? (
    <Text size="xs" c="dimmed">
      {t("schedules.fields.startsAt", { time: formatInstant(task.start_at) })}
    </Text>
  ) : null;

  return (
    <Stack gap={2}>
      <CadenceText task={task} cronTimezone={cronTimezone} />
      {startHint}
    </Stack>
  );
}

function CadenceText({ task, cronTimezone }: Props) {
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
