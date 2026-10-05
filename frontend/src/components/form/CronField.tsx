"use client";

import {
  Chip,
  Group,
  Input,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { TimePicker } from "@mantine/dates";
import { useTranslate } from "@refinedev/core";
import { useState, type CSSProperties, type ReactNode } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import {
  DEFAULT_CRON_STATE,
  HOUR_STEPS,
  MINUTE_STEPS,
  buildCron,
  parseCron,
  reconcileBuilderState,
  type CronBuilderState,
  type CronFrequency,
  type HourStep,
  type MinuteStep,
} from "@/components/form/cronBuilder";
import { NumberField } from "@/components/form/NumberField";

const WEEKDAY_ORDER = [1, 2, 3, 4, 5, 6, 0] as const;
const FREQUENCIES: CronFrequency[] = [
  "minutes",
  "hours",
  "daily",
  "weekly",
  "monthly",
];

type CronFieldProps = {
  label?: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  style?: CSSProperties;
  value: string;
  onChange?: (value: string) => void;
};

function timeString(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function parseTime(value: string): { hour: number; minute: number } | null {
  const match = /^(\d{1,2}):(\d{2})/.exec(value);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return { hour, minute };
}

function isMinuteStep(value: number): value is MinuteStep {
  return (MINUTE_STEPS as readonly number[]).includes(value);
}

function isHourStep(value: number): value is HourStep {
  return (HOUR_STEPS as readonly number[]).includes(value);
}

export function CronField({
  label,
  description,
  error,
  required,
  style,
  value,
  onChange,
}: CronFieldProps) {
  const t = useTranslate();
  const [held, setHeld] = useState<CronBuilderState>(
    () => parseCron(value) ?? DEFAULT_CRON_STATE,
  );
  const parsed = reconcileBuilderState(held, value);
  const [advanced, setAdvanced] = useState(() => parsed === null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  function emit(next: CronBuilderState) {
    onChange?.(buildCron(next));
  }

  function patch(partial: Partial<CronBuilderState>) {
    if (!parsed) return;
    const next = { ...parsed, ...partial };
    setHeld(next);
    emit(next);
  }

  const showClock =
    parsed != null &&
    (parsed.frequency === "daily" ||
      parsed.frequency === "weekly" ||
      parsed.frequency === "monthly");

  return (
    <Stack gap="xs" style={style}>
      <Switch
        label={t("form.cron.advanced")}
        checked={advanced}
        onChange={(event) => {
          if (event.currentTarget.checked) {
            if (parsed) onChange?.(buildCron(parsed));
            setAdvanced(true);
            return;
          }
          if (parsed) {
            setAdvanced(false);
            return;
          }
          setConfirmOpen(true);
        }}
      />
      {advanced ? (
        <TextInput
          label={label}
          description={description}
          required={required}
          error={error}
          value={value}
          onChange={(event) => onChange?.(event.currentTarget.value)}
        />
      ) : parsed ? (
        <Stack gap="sm">
          <Select
            label={label ?? t("form.cron.frequency")}
            description={description}
            required={required}
            error={error}
            allowDeselect={false}
            data={FREQUENCIES.map((frequency) => ({
              value: frequency,
              label: t(`form.cron.frequency.${frequency}`),
            }))}
            value={parsed.frequency}
            onChange={(next) => {
              if (
                next === "minutes" ||
                next === "hours" ||
                next === "daily" ||
                next === "weekly" ||
                next === "monthly"
              ) {
                patch({ frequency: next });
              }
            }}
          />
          {parsed.frequency === "minutes" ? (
            <Select
              label={t("form.cron.every")}
              allowDeselect={false}
              data={MINUTE_STEPS.map((step) => ({
                value: String(step),
                label: String(step),
              }))}
              value={String(parsed.everyMinutes)}
              onChange={(next) => {
                const step = Number(next);
                if (isMinuteStep(step)) patch({ everyMinutes: step });
              }}
            />
          ) : null}
          {parsed.frequency === "hours" ? (
            <Group align="flex-end" grow>
              <Select
                label={t("form.cron.every")}
                allowDeselect={false}
                data={HOUR_STEPS.map((step) => ({
                  value: String(step),
                  label: String(step),
                }))}
                value={String(parsed.everyHours)}
                onChange={(next) => {
                  const step = Number(next);
                  if (isHourStep(step)) patch({ everyHours: step });
                }}
              />
              <NumberField
                editable
                label={t("form.cron.atMinute")}
                min={0}
                max={59}
                allowDecimal={false}
                allowNegative={false}
                value={parsed.minute}
                onChange={(next) => {
                  if (typeof next !== "number" || !Number.isInteger(next)) return;
                  if (next < 0 || next > 59) return;
                  patch({ minute: next });
                }}
              />
            </Group>
          ) : null}
          {showClock ? (
            <TimePicker
              label={t("form.cron.time")}
              format="24h"
              withSeconds={false}
              value={timeString(parsed.hour, parsed.minute)}
              onChange={(next) => {
                const time = parseTime(next);
                if (!time) return;
                patch(time);
              }}
            />
          ) : null}
          {parsed.frequency === "weekly" ? (
            <Input.Wrapper label={t("form.cron.weekdays")}>
              <Chip.Group
                multiple
                value={parsed.weekdays.map(String)}
                onChange={(next) => {
                  if (next.length === 0) return;
                  patch({
                    weekdays: next
                      .map(Number)
                      .filter((day) => day >= 0 && day <= 6),
                  });
                }}
              >
                <Group gap="xs" mt={4}>
                  {WEEKDAY_ORDER.map((day) => (
                    <Chip key={day} value={String(day)}>
                      {t(`form.cron.weekday.${day}`)}
                    </Chip>
                  ))}
                </Group>
              </Chip.Group>
            </Input.Wrapper>
          ) : null}
          {parsed.frequency === "monthly" ? (
            <Select
              label={t("form.cron.dayOfMonth")}
              allowDeselect={false}
              data={Array.from({ length: 31 }, (_, index) => {
                const day = String(index + 1);
                return { value: day, label: day };
              })}
              value={String(parsed.dayOfMonth)}
              onChange={(next) => {
                const day = Number(next);
                if (day >= 1 && day <= 31) patch({ dayOfMonth: day });
              }}
            />
          ) : null}
          {parsed.frequency === "monthly" && parsed.dayOfMonth >= 29 ? (
            <Text size="sm" c="dimmed">
              {t("form.cron.monthDaySkip")}
            </Text>
          ) : null}
        </Stack>
      ) : null}
      <ConfirmActionModal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t("form.cron.replaceTitle")}
        body={t("form.cron.replaceBody")}
        confirmLabel={t("form.cron.replaceConfirm")}
        onConfirm={() => {
          setHeld(DEFAULT_CRON_STATE);
          onChange?.(buildCron(DEFAULT_CRON_STATE));
          setAdvanced(false);
          setConfirmOpen(false);
        }}
      />
    </Stack>
  );
}
