"use client";

import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

import { NumberField } from "@/components/form/NumberField";
import { SwitchField } from "@/components/form/SwitchField";
import type { EntityRecordFormValues } from "@/features/entities/types";

type ChangeLogForm = {
  values: EntityRecordFormValues;
  errors: Partial<Record<keyof EntityRecordFormValues, ReactNode>>;
  setFieldValue: (
    path: "change_log_enabled" | "change_log_retention_days",
    value: unknown,
  ) => void;
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
      <NumberField
        editable={editable}
        label={t("entities.fields.changeLogRetentionDays")}
        helper={editable ? t("entities.fields.changeLogRetentionHint") : undefined}
        min={1}
        allowDecimal={false}
        value={retentionValue}
        error={form.errors.change_log_retention_days}
        onChange={(value) =>
          form.setFieldValue("change_log_retention_days", value)
        }
      />
    </>
  );
}
