"use client";

import { Button, Checkbox, Group, Stack, Text, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslate } from "@refinedev/core";

import type {
  ModelService,
  ModelServiceFormValues,
  ModelServiceWrite,
} from "@/features/model-services/types";

type Props = {
  service?: ModelService;
  loading?: boolean;
  onSubmit: (values: ModelServiceFormValues) => void;
  onCancel: () => void;
};

export function emptyValues(): ModelServiceFormValues {
  return {
    display_name: "",
    url: "",
    model: "",
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
  };
  if (values.clear_api_key) {
    payload.clear_api_key = true;
  } else if (values.api_key.trim()) {
    payload.api_key = values.api_key;
  }
  return payload;
}

export function ModelServiceForm({
  service,
  loading,
  onSubmit,
  onCancel,
}: Props) {
  const t = useTranslate();
  const form = useForm<ModelServiceFormValues>({
    initialValues: valuesFromService(service),
    validate: {
      display_name: (value) =>
        value.trim() ? null : t("modelServices.validation.required"),
      url: (value) =>
        value.trim() ? null : t("modelServices.validation.required"),
      model: (value) =>
        value.trim() ? null : t("modelServices.validation.required"),
    },
  });
  const urlChanged = service != null && form.values.url.trim() !== service.url;
  const wireLocked = Boolean(service?.in_use);

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="sm">
        <TextInput
          label={t("modelServices.fields.display_name")}
          required
          {...form.getInputProps("display_name")}
        />
        <TextInput
          label={t("modelServices.fields.purpose")}
          value={t("modelServices.purpose.embedding")}
          disabled
        />
        <TextInput
          label={t("modelServices.fields.protocol")}
          value={t("modelServices.protocol.openai_compat")}
          disabled
        />
        <TextInput
          label={t("modelServices.fields.url")}
          description={t("modelServices.fields.url.help")}
          required
          {...form.getInputProps("url")}
        />
        <TextInput
          label={t("modelServices.fields.model")}
          required
          disabled={wireLocked}
          description={
            wireLocked ? t("modelServices.fields.model.locked") : undefined
          }
          {...form.getInputProps("model")}
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
          {...form.getInputProps("api_key")}
        />
        {service ? (
          <Checkbox
            label={t("modelServices.fields.clear_api_key")}
            {...form.getInputProps("clear_api_key", { type: "checkbox" })}
          />
        ) : null}
        {urlChanged ? (
          <Text size="sm" c="dimmed">
            {t("modelServices.fields.url.secretRequired")}
          </Text>
        ) : null}
        <Group justify="flex-end" mt="sm">
          <Button variant="default" onClick={onCancel} disabled={loading}>
            {t("actions.cancel")}
          </Button>
          <Button type="submit" loading={loading}>
            {t("actions.save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
