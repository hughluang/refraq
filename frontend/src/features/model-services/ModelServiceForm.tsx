"use client";

import { Checkbox, Stack, Text, TextInput } from "@mantine/core";

import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { FormDialog } from "@/components/form/FormDialog";
import { NumberField } from "@/components/form/NumberField";
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
    batch_limit: 32,
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
    batch_limit: service.batch_limit,
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
    batch_limit: Number(values.batch_limit),
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
  const form = useConsoleForm<ModelServiceFormValues>({
    initialValues: valuesFromService(service),
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
      batch_limit: (value) => {
        const limit = Number(value);
        if (!Number.isInteger(limit) || limit < 1 || limit > 32) {
          return t("modelServices.validation.batch_limit");
        }
        return null;
      },
    },
  });
  const urlChanged = service != null && form.values.url.trim() !== service.url;
  const inUse = Boolean(service?.in_use);

  const close = () => {
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
      onSubmit={() =>
        void form.submit(async (values) => {
          try {
            await onSubmit({
              ...values,
              timeout_sec: Number(values.timeout_sec),
              batch_limit: Number(values.batch_limit),
            });
            form.markSaved();
          } catch (error) {
            presentSaveFailure(t, error, form.applyApiError);
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
          editable
          description={
            inUse ? t("modelServices.fields.model.inUse") : undefined
          }
          {...form.fieldProps("model")}
        />
        <NumberField
          label={t("modelServices.fields.batch_limit")}
          description={t("modelServices.fields.batch_limit.help")}
          required
          editable
          min={1}
          max={32}
          allowDecimal={false}
          {...form.fieldProps("batch_limit")}
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
