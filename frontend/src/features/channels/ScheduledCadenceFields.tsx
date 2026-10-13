"use client";

import { Stack } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { CronField } from "@/components/form/CronField";
import { FieldMode } from "@/components/form/FieldMode";
import type { FieldNote } from "@/components/form/fieldNotes";
import { NumberField } from "@/components/form/NumberField";
import { SegmentedField } from "@/components/form/SegmentedField";
import { TextField } from "@/components/form/TextField";

type CadenceNotes = {
  cron?: readonly FieldNote[];
  interval_seconds?: readonly FieldNote[];
  start_at?: readonly FieldNote[];
};

type CadenceSignals = {
  cron?: string | null;
  interval_seconds?: string | null;
  start_at?: string | null;
};

type Props = {
  config: Record<string, unknown>;
  editable: boolean;
  notes?: CadenceNotes;
  openSignal?: CadenceSignals;
  onChange: (config: Record<string, unknown>) => void;
};

export function ScheduledCadenceFields({
  config,
  editable,
  notes,
  openSignal,
  onChange,
}: Props) {
  const t = useTranslate();
  const interval = typeof config.interval_seconds === "number";
  const mode = interval ? "interval" : "cron";
  const cron = typeof config.cron === "string" ? config.cron : "0 * * * *";
  const seconds = typeof config.interval_seconds === "number" ? config.interval_seconds : 3600;
  const start = typeof config.start_at === "string" ? config.start_at : "";
  const modes = [
    { value: "cron", label: t("channels.config.cadence.cron") },
    { value: "interval", label: t("channels.config.cadence.interval") },
  ];

  return (
    <Stack gap="sm">
      <SegmentedField
        editable={editable}
        fullWidth
        value={mode}
        data={modes}
        onChange={(next) => {
          if (next === "interval") {
            onChange({ ...config, cron: null, interval_seconds: seconds });
          } else {
            onChange({ ...config, cron, interval_seconds: null });
          }
        }}
      />
      {mode === "cron" ? (
        <FieldMode
          editable={editable}
          label={t("channels.config.cadence.cron")}
          notes={notes?.cron}
          openSignal={openSignal?.cron}
          value={cron}
        >
          <CronField
            label={t("channels.config.cadence.cron")}
            value={cron}
            notes={notes?.cron}
            openSignal={openSignal?.cron}
            onChange={(next) => onChange({ ...config, cron: next, interval_seconds: null })}
          />
        </FieldMode>
      ) : (
        <NumberField
          editable={editable}
          label={t("channels.config.cadence.intervalSeconds")}
          min={1}
          notes={notes?.interval_seconds}
          openSignal={openSignal?.interval_seconds}
          value={seconds}
          onChange={(value) =>
            onChange({
              ...config,
              cron: null,
              interval_seconds: typeof value === "number" ? value : seconds,
            })
          }
        />
      )}
      <TextField
        editable={editable}
        label={t("channels.config.cadence.startAt")}
        description={t("channels.config.cadence.startAtHint")}
        notes={notes?.start_at}
        openSignal={openSignal?.start_at}
        value={start}
        placeholder="2026-10-11T00:00:00Z"
        onChange={(event) => {
          const text = event.currentTarget.value.trim();
          onChange({ ...config, start_at: text || null });
        }}
      />
    </Stack>
  );
}
