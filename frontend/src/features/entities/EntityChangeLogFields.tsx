"use client";

import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import type { EntityRecordFormValues } from "@/features/entities/types";

type ChangeLogForm = {
  values: EntityRecordFormValues;
  errors: Partial<Record<keyof EntityRecordFormValues, ReactNode>>;
  setFieldValue: (
    path: "change_log_enabled" | "change_log_retention_days",
    value: string | boolean,
  ) => void;
  validateField: (path: "change_log_retention_days") => unknown;
};

type Props = {
  form: ChangeLogForm;
  editable: boolean;
};

export function EntityChangeLogFields({ form, editable }: Props) {
  const t = useTranslate();
  const days = form.values.change_log_retention_days;
  const retentionValue = editable
    ? days
    : days === ""
      ? t("entities.fields.changeLogRetentionNever")
      : days;

  return (
    <>
      <SwitchField
        editable={editable}
        label={t("entities.fields.changeLogEnabled")}
        checked={form.values.change_log_enabled}
        onChange={(event) =>
          form.setFieldValue("change_log_enabled", event.currentTarget.checked)
        }
      />
      <TextField
        editable={editable}
        label={t("entities.fields.changeLogRetentionDays")}
        helper={editable ? t("entities.fields.changeLogRetentionHint") : undefined}
        inputMode="decimal"
        value={retentionValue}
        error={form.errors.change_log_retention_days}
        onChange={(event) => {
          const hadError = Boolean(form.errors.change_log_retention_days);
          form.setFieldValue(
            "change_log_retention_days",
            event.currentTarget.value,
          );
          if (hadError) void form.validateField("change_log_retention_days");
        }}
      />
    </>
  );
}
