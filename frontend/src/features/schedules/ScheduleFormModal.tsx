"use client";

import {
  Button,
  Group,
  Input,
  Modal,
  SegmentedControl,
  Skeleton,
  Stack,
  Text,
} from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import { useForm } from "@mantine/form";
import { useGetLocale, useNotification, useTranslate } from "@refinedev/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { CronField } from "@/components/form/CronField";
import { DEFAULT_DAILY_CRON } from "@/components/form/cronBuilder";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import {
  createSourceSchedule,
  patchSchedule,
  previewCron,
} from "@/features/schedules/api";
import { describeCron } from "@/features/schedules/cronDescription";
import {
  INTERVAL_UNITS,
  intervalToSeconds,
  isAllowedInterval,
  isPositiveInteger,
  splitIntervalSeconds,
  type IntervalUnit,
} from "@/features/schedules/intervalUnits";
import {
  MAX_CADENCE_SECONDS,
  isAllowedTimeoutInput,
  timeoutFromTask,
  timeoutPayload,
} from "@/features/schedules/runningTimeoutField";
import { scheduleKindFromTask } from "@/features/schedules/scheduleKindField";
import {
  isAllowedStartAt,
  startAtToWall,
  wallToStartAt,
} from "@/features/schedules/startAtField";
import type { ScheduledTask } from "@/features/schedules/types";
import { useDisplayZoneId, useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

type CadenceMode = "clock" | "interval";

type FormValues = {
  kind: "structure" | "join_detection";
  cadence: CadenceMode;
  cron: string;
  intervalAmount: number | string;
  intervalUnit: IntervalUnit;
  running_timeout_sec: number | "";
  /** Wall time in the Schedule Timezone; null = start immediately. */
  startWall: string | null;
  enabled: boolean;
  name: string;
};

function valuesFromTask(
  task: ScheduledTask | null,
  cronTimezone: string,
): FormValues {
  const seconds = task?.interval_seconds;
  const split =
    seconds != null
      ? splitIntervalSeconds(seconds)
      : { amount: 1, unit: "hours" as const };
  return {
    kind: scheduleKindFromTask(task?.work_kind),
    cadence: seconds != null ? "interval" : "clock",
    cron: task?.cron?.trim() || DEFAULT_DAILY_CRON,
    intervalAmount: split.amount,
    intervalUnit: split.unit,
    running_timeout_sec: timeoutFromTask(task?.running_timeout_sec),
    startWall: startAtToWall(task?.start_at, cronTimezone),
    enabled: task?.enabled ?? true,
    name: task?.name ?? "",
  };
}

function isCadenceRejected(error: unknown): boolean {
  return error instanceof ApiError && error.status === 400;
}

type ScheduleFormModalProps = {
  opened: boolean;
  onClose: () => void;
  onSaved: () => void;
  sourceId?: string;
  sourceLabel?: string;
  schedule?: ScheduledTask | null;
  cronTimezone: string;
};

export function ScheduleFormModal({
  opened,
  onClose,
  onSaved,
  sourceId,
  sourceLabel,
  schedule,
  cronTimezone,
}: ScheduleFormModalProps) {
  const t = useTranslate();
  const title = sourceLabel
    ? `${t("schedules.form.title")} · ${sourceLabel}`
    : t("schedules.form.title");

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="lg">
      {opened ? (
        <ScheduleForm
          key={schedule?.id ?? `create:${sourceId ?? ""}`}
          onClose={onClose}
          onSaved={onSaved}
          sourceId={sourceId}
          schedule={schedule ?? null}
          cronTimezone={cronTimezone}
        />
      ) : null}
    </Modal>
  );
}

function ScheduleForm({
  onClose,
  onSaved,
  sourceId,
  schedule,
  cronTimezone,
}: {
  onClose: () => void;
  onSaved: () => void;
  sourceId?: string;
  schedule: ScheduledTask | null;
  cronTimezone: string;
}) {
  const t = useTranslate();
  const locale = useGetLocale()() ?? "en-US";
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const displayZone = useDisplayZoneId();
  const [saving, setSaving] = useState(false);
  const form = useForm<FormValues>({
    initialValues: valuesFromTask(schedule, cronTimezone),
  });
  const cron = form.values.cron.trim();
  const startAt = wallToStartAt(form.values.startWall, cronTimezone);
  const [debouncedCron, setDebouncedCron] = useState(cron);
  const skipDebounce = useRef(true);

  useEffect(() => {
    if (skipDebounce.current) {
      skipDebounce.current = false;
      setDebouncedCron(cron);
      return;
    }
    const timer = window.setTimeout(() => setDebouncedCron(cron), 400);
    return () => window.clearTimeout(timer);
  }, [cron]);

  const clock = form.values.cadence === "clock";
  const startTooFar = !isAllowedStartAt(startAt);
  const preview = useQuery({
    queryKey: ["schedules", "cron-preview", debouncedCron, startAt],
    queryFn: () => previewCron(debouncedCron, startAt),
    enabled: clock && !startTooFar,
    retry: false,
    staleTime: 0,
  });

  const debouncing = clock && cron !== debouncedCron;
  const inFlight = clock && preview.isFetching;
  const previewPaused = clock && preview.fetchStatus === "paused";
  const showSkeleton = debouncing || inFlight;
  const settled = clock && !debouncing && !preview.isFetching && !previewPaused;
  const rejected = settled && preview.isError && isCadenceRejected(preview.error);
  const previewFailed =
    !debouncing &&
    !inFlight &&
    (previewPaused ||
      (clock && preview.isError && !isCadenceRejected(preview.error)));
  const previewReady = settled && preview.isSuccess;
  const intervalAmountOk = isPositiveInteger(form.values.intervalAmount);
  const intervalValid = isAllowedInterval(
    form.values.intervalAmount,
    form.values.intervalUnit,
  );
  const canSave = !startTooFar && (clock ? previewReady : intervalValid);
  const sentence =
    previewReady && preview.data
      ? describeCron(debouncedCron, locale, t)
      : null;

  async function handleSave() {
    const timeoutInput = form.values.running_timeout_sec;
    if (
      typeof timeoutInput === "number" &&
      Number.isInteger(timeoutInput) &&
      timeoutInput > MAX_CADENCE_SECONDS
    ) {
      form.setFieldError(
        "running_timeout_sec",
        t("schedules.validation.runningTimeoutMax"),
      );
      return;
    }
    if (!isAllowedTimeoutInput(timeoutInput)) {
      form.setFieldError(
        "running_timeout_sec",
        t("schedules.validation.runningTimeout"),
      );
      return;
    }
    if (!canSave) return;
    setSaving(true);
    try {
      const name = form.values.name.trim();
      const running_timeout_sec = timeoutPayload(timeoutInput);
      const cadenceBody =
        form.values.cadence === "interval"
          ? {
              interval_seconds: intervalToSeconds(
                Number(form.values.intervalAmount),
                form.values.intervalUnit,
              ),
              cron: null as string | null,
              running_timeout_sec,
              start_at: startAt,
              enabled: form.values.enabled,
              name,
            }
          : {
              cron,
              interval_seconds: null as number | null,
              running_timeout_sec,
              start_at: startAt,
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
        message: problemMessage(t, err, String(err)),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
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
            form.setFieldValue(
              "kind",
              value === "join_detection" ? "join_detection" : "structure",
            );
          }}
        />
      )}
      <Input.Wrapper label={t("schedules.fields.cadence")}>
        <SegmentedControl
          fullWidth
          mt={4}
          value={form.values.cadence}
          onChange={(value) => {
            const cadence: CadenceMode = value === "interval" ? "interval" : "clock";
            if (cadence === "clock" && !form.values.cron.trim()) {
              form.setFieldValue("cron", DEFAULT_DAILY_CRON);
            }
            form.setFieldValue("cadence", cadence);
          }}
          data={[
            { value: "clock", label: t("schedules.cadence.clock") },
            { value: "interval", label: t("schedules.cadence.interval") },
          ]}
        />
      </Input.Wrapper>
      <Text size="xs" c="dimmed">
        {clock
          ? t("schedules.cadence.clockHint")
          : t("schedules.cadence.intervalHint")}
      </Text>
      {clock ? (
        <CronField
          label={t("schedules.fields.cron")}
          description={t("schedules.fields.cronTimezoneHint", {
            zone: cronTimezone,
          })}
          error={rejected ? t("schedules.validation.cron") : undefined}
          value={form.values.cron}
          onChange={(next) => form.setFieldValue("cron", next)}
        />
      ) : (
        <Group align="flex-start" grow>
          <NumberField
            editable
            label={t("schedules.interval.amount")}
            min={1}
            allowDecimal={false}
            allowNegative={false}
            value={form.values.intervalAmount}
            error={
              intervalValid
                ? undefined
                : intervalAmountOk
                  ? t("schedules.validation.intervalMax")
                  : t("schedules.validation.interval")
            }
            onChange={(value) => {
              if (typeof value === "number" || typeof value === "string") {
                form.setFieldValue("intervalAmount", value);
              }
            }}
          />
          <SelectField
            editable
            allowDeselect={false}
            label={t("schedules.interval.unit")}
            data={INTERVAL_UNITS.map((unit) => ({
              value: unit,
              label: t(`schedules.interval.unit.${unit}`),
            }))}
            value={form.values.intervalUnit}
            onChange={(value) => {
              if (
                value === "seconds" ||
                value === "minutes" ||
                value === "hours" ||
                value === "days"
              ) {
                form.setFieldValue("intervalUnit", value);
              }
            }}
          />
        </Group>
      )}
      <DateTimePicker
        label={t("schedules.fields.startAt")}
        description={t("schedules.fields.startAtHint", { zone: cronTimezone })}
        placeholder={t("schedules.fields.startAtPlaceholder")}
        clearable
        valueFormat="YYYY-MM-DD HH:mm"
        value={form.values.startWall}
        error={startTooFar ? t("schedules.validation.startAtMax") : undefined}
        onChange={(value) => form.setFieldValue("startWall", value || null)}
      />
      {clock && showSkeleton ? <Skeleton height={96} radius="sm" /> : null}
      {clock && previewFailed ? (
        <Stack gap="xs">
          <Text size="sm">{t("schedules.form.previewFailed")}</Text>
          <Group>
            <Button
              variant="light"
              size="xs"
              onClick={() => void preview.refetch()}
            >
              {t("schedules.form.previewRetry")}
            </Button>
          </Group>
        </Stack>
      ) : null}
      {previewReady && preview.data ? (
        <Stack gap={4}>
          {sentence ? <Text size="sm">{sentence}</Text> : null}
          <Text size="sm" fw={500}>
            {t("schedules.form.previewTitle", {
              zone:
                displayZone ?? t("account.fields.displayTimezone.browser"),
            })}
          </Text>
          {preview.data.next_run_ats.map((instant) => (
            <Text key={instant} size="sm">
              {formatInstant(instant)}
            </Text>
          ))}
          {form.values.enabled ? null : (
            <Text size="sm" c="dimmed">
              {t("schedules.form.previewWhenEnabled")}
            </Text>
          )}
        </Stack>
      ) : null}
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
        <Button variant="default" onClick={onClose} disabled={saving}>
          {t("common.cancel")}
        </Button>
        <Button
          loading={saving || showSkeleton}
          disabled={!canSave}
          onClick={() => void handleSave()}
        >
          {t("common.save")}
        </Button>
      </Group>
    </Stack>
  );
}
