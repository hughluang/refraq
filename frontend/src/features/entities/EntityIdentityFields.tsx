"use client";

import { useTranslate } from "@refinedev/core";

import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";

type IdentityFormApi = {
  getInputProps: (path: string) => object;
};

type Props = {
  form: IdentityFormApi;
  tableName: { mode: "create" } | { mode: "readonly"; value: string };
  editable: boolean;
};

export function EntityIdentityFields({ form, tableName, editable }: Props) {
  const t = useTranslate();

  return (
    <>
      {tableName.mode === "readonly" ? (
        <TextField
          label={t("entities.fields.tableName")}
          editable={false}
          value={tableName.value}
        />
      ) : (
        <TextField
          label={t("entities.fields.tableName")}
          required
          editable={editable}
          {...form.getInputProps("table_name")}
        />
      )}
      <TextField
        label={t("entities.fields.name")}
        required={editable}
        editable={editable}
        {...form.getInputProps("name")}
      />
      <TextareaField
        label={t("entities.fields.description")}
        required={editable}
        editable={editable}
        minRows={2}
        {...form.getInputProps("description")}
      />
    </>
  );
}
