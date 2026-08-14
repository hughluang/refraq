"use client";

import {
  Button,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Switch,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import {
  deleteSourceSchedule,
  getSourceSchedule,
  patchSchedule,
  putSourceSchedule,
} from "@/features/schedules/api";
import type { ScheduledTask } from "@/features/schedules/types";
import { ApiError } from "@/lib/api";

const PRESETS = [
  { value: "hourly", cron: "0 * * * *" },
  { value: "daily", cron: "0 2 * * *" },
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
  cadence: CadenceKind;
  cron: string;
  interval_seconds: number | string;
  schedule_timezone: string;
  enabled: boolean;
  name: string;
};

function inferCadence(task: ScheduledTask | null): CadenceKind {
  if (!task) return "daily";
  if (task.interval_seconds) return "interval";
  const match = PRESETS.find(
    (preset) => preset.value !== "custom" && preset.cron === task.cron,
  );
  return match?.value ?? "custom";
}

function valuesFromTask(task: ScheduledTask | null): FormValues {
  return {
    cadence: inferCadence(task),
    cron: task?.cron ?? "0 2 * * *",
    interval_seconds: task?.interval_seconds ?? 3600,
    schedule_timezone: task?.schedule_timezone ?? "UTC",
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
  const [existing, setExisting] = useState<ScheduledTask | null>(
    schedule ?? null,
  );
  const form = useForm<FormValues>({
    initialValues: valuesFromTask(schedule ?? null),
  });

  useEffect(() => {
    if (!opened) return;
    let cancelled = false;
    async function load() {
      if (schedule) {
        setExisting(schedule);
        form.setValues(valuesFromTask(schedule));
        return;
      }
      if (!sourceId) return;
      try {
        const data = await getSourceSchedule(sourceId);
        if (cancelled) return;
        setExisting(data.schedule);
        form.setValues(valuesFromTask(data.schedule));
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setExisting(null);
          form.setValues(valuesFromTask(null));
          return;
        }
        open?.({
          type: "error",
          message: err instanceof ApiError ? err.detail : String(err),
        });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the modal target changes
  }, [opened, sourceId, schedule?.id]);

  async function handleSave() {
    setLoading(true);
    try {
      const timezone = form.values.schedule_timezone.trim() || "UTC";
      const name = form.values.name.trim() || null;
      if (sourceId) {
        const body =
          form.values.cadence === "interval"
            ? {
                kind: "structure" as const,
                interval_seconds: Number(form.values.interval_seconds),
                cron: null,
                schedule_timezone: timezone,
                enabled: form.values.enabled,
                name,
              }
            : {
                kind: "structure" as const,
                cron:
                  form.values.cadence === "custom"
                    ? form.values.cron.trim()
                    : (PRESETS.find((p) => p.value === form.values.cadence)
                        ?.cron ?? form.values.cron.trim()),
                interval_seconds: null,
                schedule_timezone: timezone,
                enabled: form.values.enabled,
                name,
              };
        await putSourceSchedule(sourceId, body);
      } else if (existing) {
        const body =
          form.values.cadence === "interval"
            ? {
                interval_seconds: Number(form.values.interval_seconds),
                cron: null as string | null,
                schedule_timezone: timezone,
                enabled: form.values.enabled,
                name,
              }
            : {
                cron:
                  form.values.cadence === "custom"
                    ? form.values.cron.trim()
                    : (PRESETS.find((p) => p.value === form.values.cadence)
                        ?.cron ?? form.values.cron.trim()),
                interval_seconds: null as number | null,
                schedule_timezone: timezone,
                enabled: form.values.enabled,
                name,
              };
        await patchSchedule(existing.id, body);
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

  async function handleDelete() {
    if (!sourceId || !existing) return;
    setLoading(true);
    try {
      await deleteSourceSchedule(sourceId);
      open?.({ type: "success", message: t("schedules.delete.success") });
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
        <Select
          label={t("schedules.fields.cadence")}
          data={PRESETS.map((preset) => ({
            value: preset.value,
            label: t(`schedules.preset.${preset.value}`),
          }))}
          {...form.getInputProps("cadence")}
        />
        {form.values.cadence === "interval" ? (
          <NumberInput
            label={t("schedules.fields.intervalSeconds")}
            min={1}
            {...form.getInputProps("interval_seconds")}
          />
        ) : (
          <TextInput
            label={t("schedules.fields.cron")}
            disabled={form.values.cadence !== "custom"}
            value={
              form.values.cadence === "custom"
                ? form.values.cron
                : (PRESETS.find((p) => p.value === form.values.cadence)?.cron ??
                  form.values.cron)
            }
            onChange={(event) =>
              form.setFieldValue("cron", event.currentTarget.value)
            }
          />
        )}
        <Select
          label={t("schedules.fields.timezone")}
          data={TIMEZONES}
          searchable
          {...form.getInputProps("schedule_timezone")}
        />
        <TextInput
          label={t("schedules.fields.name")}
          {...form.getInputProps("name")}
        />
        <Switch
          label={t("schedules.fields.enabled")}
          checked={form.values.enabled}
          onChange={(event) =>
            form.setFieldValue("enabled", event.currentTarget.checked)
          }
        />
        <Group justify="space-between">
          {sourceId && existing ? (
            <Button
              color="red"
              variant="light"
              loading={loading}
              onClick={() => void handleDelete()}
            >
              {t("schedules.delete")}
            </Button>
          ) : (
            <span />
          )}
          <Group>
            <Button variant="default" onClick={onClose} disabled={loading}>
              {t("common.cancel")}
            </Button>
            <Button loading={loading} onClick={() => void handleSave()}>
              {t("common.save")}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
