"use client";

import { useTranslate } from "@refinedev/core";

import { RowActions } from "@/components/display/RowActions";
import { deleteSchedule, runSchedule } from "@/features/schedules/api";
import { isChannelRunSchedule } from "@/features/schedules/scheduleIdentity";
import type { ScheduledTask } from "@/features/schedules/types";

type Props = {
  task: ScheduledTask;
  onEdit: () => void;
  onJobs: () => void;
  onChanged: () => void;
};

export function ScheduleRowActions({ task, onEdit, onJobs, onChanged }: Props) {
  const t = useTranslate();
  const recordName = task.name || task.key;
  const channelRun = isChannelRunSchedule(task);

  return (
    <RowActions
      recordName={recordName}
      verbs={[
        {
          key: "run",
          label: t("schedules.run"),
          disabledReason: channelRun ? t("schedules.run.unavailable") : undefined,
          action: {
            safety: "immediate",
            recordName,
            outcome: t("schedules.run.outcome"),
            execute: () => runSchedule(task.id),
            onSuccess: () => onChanged(),
          },
        },
        {
          key: "jobs",
          label: t("jobs.scheduleJobs.open"),
          safety: "immediate",
          onClick: onJobs,
        },
        {
          key: "edit",
          label: t("schedules.edit"),
          disabledReason: channelRun ? t("schedules.edit.unavailable") : undefined,
          safety: "immediate",
          onClick: onEdit,
        },
        {
          key: "delete",
          label: t("schedules.delete"),
          color: "red",
          disabledReason:
            task.deletable === false ? t("schedules.delete.unavailable") : undefined,
          action: {
            safety: "confirm",
            recordName,
            title: t("schedules.delete.confirmTitle"),
            consequence: t("schedules.delete.consequence"),
            confirmLabel: t("schedules.delete"),
            confirmColor: "red",
            outcome: t("schedules.delete.success"),
            execute: () => deleteSchedule(task.id),
            onSuccess: () => onChanged(),
          },
        },
      ]}
    />
  );
}
