"use client";

import { TextInput, Textarea } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

type IdentityFormApi = {
  getInputProps: (path: string) => object;
};

type Props = {
  form: IdentityFormApi;
  tableName: { mode: "create" } | { mode: "readonly"; value: string };
  disabled?: boolean;
};

export function EntityIdentityFields({
  form,
  tableName,
  disabled = false,
}: Props) {
  const t = useTranslate();

  return (
    <>
      {tableName.mode === "readonly" ? (
        <TextInput
          label={t("entities.fields.tableName")}
          value={tableName.value}
          disabled
        />
      ) : (
        <TextInput
          label={t("entities.fields.tableName")}
          required
          {...form.getInputProps("table_name")}
          disabled={disabled}
        />
      )}
      <TextInput
        label={t("entities.fields.name")}
        required
        {...form.getInputProps("name")}
        disabled={disabled}
      />
      <Textarea
        label={t("entities.fields.description")}
        required
        minRows={2}
        {...form.getInputProps("description")}
        disabled={disabled}
      />
    </>
  );
}
