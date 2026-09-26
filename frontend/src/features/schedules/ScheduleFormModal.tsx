"use client";

import { Button, Group, Modal, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import {
  createSourceSchedule,
  patchSchedule,
} from "@/features/schedules/api";
import {
  isAllowedTimeoutInput,
  timeoutFromTask,
  timeoutPayload,
} from "@/features/schedules/runningTimeoutField";
import {
  dailyPresetLabelKey,
  defaultCron,
  isDailyCron,
  scheduleKindFromTask,
} from "@/features/schedules/scheduleKindField";
import type { ScheduledTask } from "@/features/schedules/types";
import { CronField } from "@/components/form/CronField";
import type { PresetCron } from "@/components/form/cronPhrase";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import { ApiError } from "@/lib/api";

const PRESETS = [
  { value: "hourly", cron: "0 * * * *" },
  { value: "daily", cron: "" },
  { value: "weekly", cron: "0 2 * * 1" },
  { value: "custom", cron: "" },
  { value: "interval", cron: "" },
] as const;

const TIMEZONES = [
  "UTC",
  "Asia/Shanghai",
  "America/Los_Angeles",
  "America/New_York",
  "Europe/London",
];

type CadenceKind = (typeof PRESETS)[number]["value"];

type FormValues = {
  kind: "structure" | "join_detection";
  cadence: CadenceKind;
  cron: string;
  interval_seconds: number | string;
  schedule_timezone: string;
  running_timeout_sec: number | "";
  enabled: boolean;
  name: string;
};

function displayedCron(
  cadence: "hourly" | "daily" | "weekly",
  kind: FormValues["kind"],
): PresetCron {
  if (cadence === "daily") return defaultCron(kind);
  if (cadence === "hourly") return "0 * * * *";
  return "0 2 * * 1";
}

function presetCron(
  cadence: CadenceKind,
  kind: FormValues["kind"],
): PresetCron | null {
  if (cadence === "custom" || cadence === "interval") return null;
  return displayedCron(cadence, kind);
}

function inferCadence(
  task: ScheduledTask | null,
  kind: ReturnType<typeof scheduleKindFromTask>,
): CadenceKind {
  if (!task) return "daily";
  if (task.interval_seconds) return "interval";
  if (isDailyCron(task.cron, kind)) return "daily";
  const match = PRESETS.find(
    (preset) =>
      preset.value !== "custom" &&
      preset.value !== "daily" &&
      preset.cron === task.cron,
  );
  return match?.value ?? "custom";
}

function valuesFromTask(task: ScheduledTask | null): FormValues {
  const kind = scheduleKindFromTask(task?.work_kind);
  return {
    kind,
    cadence: inferCadence(task, kind),
    cron: task?.cron ?? defaultCron(kind),
    interval_seconds: task?.interval_seconds ?? 3600,
    schedule_timezone: task?.schedule_timezone ?? "UTC",
    running_timeout_sec: timeoutFromTask(task?.running_timeout_sec),
    enabled: task?.enabled ?? true,
    name: task?.name ?? "",
  };
}

type ScheduleFormModalProps = {
  opened: boolean;
  onClose: () => void;
  onSaved: () => void;
  sourceId?: string;
  sourceLabel?: string;
  schedule?: ScheduledTask | null;
};

export function ScheduleFormModal({
  opened,
  onClose,
  onSaved,
  sourceId,
  sourceLabel,
  schedule,
}: ScheduleFormModalProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [loading, setLoading] = useState(false);
  const form = useForm<FormValues>({
    initialValues: valuesFromTask(schedule ?? null),
  });

  useEffect(() => {
    if (!opened) return;
    form.setValues(valuesFromTask(schedule ?? null));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the modal target changes
  }, [opened, sourceId, schedule?.id]);

  async function handleSave() {
    const timeoutInput = form.values.running_timeout_sec;
    if (!isAllowedTimeoutInput(timeoutInput)) {
      form.setFieldError(
        "running_timeout_sec",
        t("schedules.validation.runningTimeout"),
      );
      return;
    }
    setLoading(true);
    try {
      const timezone = form.values.schedule_timezone.trim() || "UTC";
      const name = form.values.name.trim();
      const running_timeout_sec = timeoutPayload(timeoutInput);
      const cadenceBody =
        form.values.cadence === "interval"
          ? {
              interval_seconds: Number(form.values.interval_seconds),
              cron: null as string | null,
              schedule_timezone: timezone,
              running_timeout_sec,
              enabled: form.values.enabled,
              name,
            }
          : {
              cron: form.values.cron.trim(),
              interval_seconds: null as number | null,
              schedule_timezone: timezone,
              running_timeout_sec,
              enabled: form.values.enabled,
              name,
            };
      if (schedule) {
        await patchSchedule(schedule.id, cadenceBody);
      } else if (sourceId) {
        await createSourceSchedule(sourceId, {
          kind: form.values.kind,
          ...cadenceBody,
        });
      } else {
        return;
      }
      open?.({ type: "success", message: t("schedules.save.success") });
      onSaved();
      onClose();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setLoading(false);
    }
  }

  const title = sourceLabel
    ? `${t("schedules.form.title")} · ${sourceLabel}`
    : t("schedules.form.title");

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="md">
      <Stack gap="sm">
        {schedule ? null : (
          <SelectField
            editable
            label={t("schedules.fields.kind")}
            data={[
              {
                value: "structure",
                label: t("schedules.workKind.structure"),
              },
              {
                value: "join_detection",
                label: t("schedules.workKind.join_detection"),
              },
            ]}
            value={form.values.kind}
            onChange={(value) => {
              const kind =
                value === "join_detection" ? "join_detection" : "structure";
              const next: Partial<FormValues> = { kind };
              if (form.values.cadence === "daily") {
                next.cron = defaultCron(kind);
              }
              form.setValues(next);
            }}
          />
        )}
        <SelectField
          editable
          allowDeselect={false}
          label={t("schedules.fields.cadence")}
          data={PRESETS.map((preset) => ({
            value: preset.value,
            label:
              preset.value === "daily"
                ? t(dailyPresetLabelKey(form.values.kind))
                : t(`schedules.preset.${preset.value}`),
          }))}
          value={form.values.cadence}
          onChange={(value) => {
            const cadence = value as CadenceKind;
            const next: Partial<FormValues> = { cadence };
            const preset = presetCron(cadence, form.values.kind);
            if (preset != null) next.cron = preset;
            form.setValues(next);
          }}
        />
        {form.values.cadence === "interval" ? (
          <NumberField
            editable
            label={t("schedules.fields.intervalSeconds")}
            min={1}
            {...form.getInputProps("interval_seconds")}
          />
        ) : form.values.cadence === "custom" ? (
          <CronField
            editable
            label={t("schedules.fields.cron")}
            value={form.values.cron}
            onChange={(cron) => form.setFieldValue("cron", cron)}
          />
        ) : (
          <CronField
            editable={false}
            label={t("schedules.fields.cron")}
            value={displayedCron(form.values.cadence, form.values.kind)}
          />
        )}
        <SelectField
          editable
          label={t("schedules.fields.timezone")}
          data={TIMEZONES}
          searchable
          {...form.getInputProps("schedule_timezone")}
        />
        <NumberField
          editable
          label={t("schedules.fields.runningTimeout")}
          description={t("schedules.fields.runningTimeoutHelp")}
          min={1}
          allowDecimal={false}
          allowNegative={false}
          value={form.values.running_timeout_sec}
          error={form.errors.running_timeout_sec}
          onChange={(value) => {
            if (value === "" || value == null) {
              form.setFieldValue("running_timeout_sec", "");
              return;
            }
            if (typeof value === "number") {
              form.setFieldValue("running_timeout_sec", value);
            }
          }}
        />
        <TextField
          editable
          label={t("schedules.fields.name")}
          {...form.getInputProps("name")}
        />
        <SwitchField
          editable
          label={t("schedules.fields.enabled")}
          checked={form.values.enabled}
          onChange={(event) =>
            form.setFieldValue("enabled", event.currentTarget.checked)
          }
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={loading}>
            {t("common.cancel")}
          </Button>
          <Button loading={loading} onClick={() => void handleSave()}>
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
