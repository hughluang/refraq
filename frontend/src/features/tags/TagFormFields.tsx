"use client";

import { Stack } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { TextField } from "@/components/form/TextField";
import type { UseConsoleFormReturn } from "@/components/form/useConsoleForm";
import type { TagFormValues } from "@/features/tags/types";

type Props = {
  form: UseConsoleFormReturn<TagFormValues>;
  editable: boolean;
};

export function TagFormFields({ form, editable }: Props) {
  const t = useTranslate();
  return (
    <Stack>
      <TextField
        editable={editable}
        required
        label={t("tags.fields.name")}
        {...form.fieldProps("name")}
      />
      <TextField
        editable={editable}
        label={t("tags.fields.description")}
        {...form.fieldProps("description")}
      />
    </Stack>
  );
}
