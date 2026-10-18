"use client";

import { Checkbox, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";

import { FormDialog } from "@/components/form/FormDialog";
import { NumberField } from "@/components/form/NumberField";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { useTranslate } from "@refinedev/core";

import type {
  ModelService,
  ModelServiceFormValues,
  ModelServiceWrite,
} from "@/features/model-services/types";

type Props = {
  opened: boolean;
  service?: ModelService;
  onSubmit: (values: ModelServiceFormValues) => Promise<void>;
  onClose: () => void;
};

export function emptyValues(): ModelServiceFormValues {
  return {
    display_name: "",
    url: "",
    model: "",
    timeout_sec: 30,
    api_key: "",
    clear_api_key: false,
  };
}

export function valuesFromService(
  service?: ModelService,
): ModelServiceFormValues {
  if (!service) return emptyValues();
  return {
    display_name: service.display_name,
    url: service.url,
    model: service.model,
    timeout_sec: service.timeout_sec,
    api_key: "",
    clear_api_key: false,
  };
}

export function servicePayload(
  values: ModelServiceFormValues,
): ModelServiceWrite {
  const payload: ModelServiceWrite = {
    display_name: values.display_name.trim(),
    url: values.url.trim(),
    model: values.model.trim(),
    timeout_sec: Number(values.timeout_sec),
  };
  if (values.clear_api_key) {
    payload.clear_api_key = true;
  } else if (values.api_key.trim()) {
    payload.api_key = values.api_key;
  }
  return payload;
}

export function ModelServiceForm({
  opened,
  service,
  onSubmit,
  onClose,
}: Props) {
  const t = useTranslate();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<ModelServiceFormValues>({
    initialValues: valuesFromService(service),
    onValuesChange: () => setSaveFailure(null),
    validate: {
      display_name: (value) =>
        value.trim() ? null : t("modelServices.validation.required"),
      url: (value) =>
        value.trim() ? null : t("modelServices.validation.required"),
      model: (value) =>
        value.trim() ? null : t("modelServices.validation.required"),
      timeout_sec: (value) => {
        const seconds = Number(value);
        if (!Number.isInteger(seconds) || seconds < 15 || seconds > 300) {
          return t("modelServices.validation.timeout");
        }
        return null;
      },
    },
  });
  const urlChanged = service != null && form.values.url.trim() !== service.url;
  const wireLocked = Boolean(service?.in_use);

  const close = () => {
    setSaveFailure(null);
    form.reset();
    onClose();
  };

  return (
    <FormDialog
      opened={opened}
      onClose={close}
      size="lg"
      title={service ? t("modelServices.edit") : t("modelServices.create")}
      dirty={form.dirty}
      submitting={form.submitting}
      submitLabel={t("actions.save")}
      summary={<FormErrorSummary failure={saveFailure} />}
      onSubmit={() =>
        void form.submit(async (values) => {
          try {
            await onSubmit(values);
            form.markSaved();
            setSaveFailure(null);
          } catch (error) {
            setSaveFailure(
              saveFailureFrom(
                t,
                error,
                form.applyApiError(error),
                t("common.error.loadFailed"),
              ),
            );
          }
        })
      }
    >
      <Stack gap="sm">
        <TextField
          label={t("modelServices.fields.display_name")}
          required
          editable
          {...form.fieldProps("display_name")}
        />
        <TextField
          label={t("modelServices.fields.purpose")}
          editable={false}
          value={t("modelServices.purpose.embedding")}
        />
        <TextField
          label={t("modelServices.fields.protocol")}
          editable={false}
          value={t("modelServices.protocol.openai_compat")}
        />
        <TextField
          label={t("modelServices.fields.url")}
          description={t("modelServices.fields.url.help")}
          required
          editable
          {...form.fieldProps("url")}
        />
        <TextField
          label={t("modelServices.fields.model")}
          required
          editable={!wireLocked}
          description={
            wireLocked ? t("modelServices.fields.model.locked") : undefined
          }
          {...form.fieldProps("model")}
        />
        <NumberField
          label={t("modelServices.fields.timeout_sec")}
          description={t("modelServices.fields.timeout_sec.help")}
          required
          editable
          min={15}
          max={300}
          allowDecimal={false}
          {...form.fieldProps("timeout_sec")}
        />
        <TextInput
          label={t("modelServices.fields.api_key")}
          type="password"
          autoComplete="new-password"
          description={
            service?.has_secret
              ? t("modelServices.fields.api_key.configured")
              : t("modelServices.fields.api_key.help")
          }
          {...form.fieldProps("api_key")}
        />
        {service ? (
          <Checkbox
            label={t("modelServices.fields.clear_api_key")}
            {...form.fieldProps("clear_api_key", { type: "checkbox" })}
          />
        ) : null}
        {urlChanged ? (
          <Text size="sm" c="dimmed">
            {t("modelServices.fields.url.secretRequired")}
          </Text>
        ) : null}
      </Stack>
    </FormDialog>
  );
}
