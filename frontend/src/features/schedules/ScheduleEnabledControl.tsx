"use client";

import { useTranslate } from "@refinedev/core";

import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { SwitchField } from "@/components/form/SwitchField";
import { patchSchedule } from "@/features/schedules/api";
import type { ScheduledTask } from "@/features/schedules/types";

type Props = {
  task: ScheduledTask;
  editable: boolean;
  recordName: string;
  onChanged: () => void | Promise<void>;
};

export function ScheduleEnabledControl({
  task,
  editable,
  recordName,
  onChanged,
}: Props) {
  const t = useTranslate();
  const mutation = useConsoleMutation();
  const name = recordName.trim() || task.name || task.key;
  return (
    <SwitchField
      editable={editable}
      checked={task.enabled}
      aria-busy={mutation.submitting || undefined}
      onChange={(event) => {
        const next = event.currentTarget.checked;
        mutation.run({
          safety: "undoable",
          key: task.id,
          recordName: name,
          outcome: next
            ? t("schedules.enabled.outcome")
            : t("schedules.disabled.outcome"),
          execute: () => patchSchedule(task.id, { enabled: next }),
          undo: () => patchSchedule(task.id, { enabled: !next }),
          onSuccess: () => onChanged(),
        });
      }}
    />
  );
}
