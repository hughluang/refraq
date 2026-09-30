"use client";

import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { DictionaryFormFields } from "@/features/dictionaries/DictionaryFormFields";
import { createDictionary } from "@/features/dictionaries/api";
import {
  EMPTY_DICTIONARY_FORM,
  dictionaryFormErrors,
  entriesFromForm,
} from "@/features/dictionaries/dictionaryForm";
import type { DictionaryFormValues } from "@/features/dictionaries/types";
import { ApiError } from "@/lib/api";

export type CreatedDictionary = {
  id: string;
  name: string;
  display_name: string;
};

type Props = {
  opened: boolean;
  onClose: () => void;
  onCreated: (created: CreatedDictionary) => void;
};

export function CreateDictionaryModal({ opened, onClose, onCreated }: Props) {
  const t = useTranslate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<DictionaryFormValues>({
    initialValues: EMPTY_DICTIONARY_FORM,
    validate: (values) => dictionaryFormErrors(values, t),
  });

  const close = () => {
    form.setValues(EMPTY_DICTIONARY_FORM);
    form.resetDirty();
    setError(null);
    onClose();
  };

  const submit = async (values: DictionaryFormValues) => {
    setBusy(true);
    setError(null);
    try {
      const description = values.description.trim();
      const created = await createDictionary({
        name: values.name.trim(),
        display_name: values.display_name.trim(),
        ...(description ? { description } : {}),
        entries: entriesFromForm(values.entries),
      });
      onCreated({
        id: created.dictionary.id,
        name: created.dictionary.name,
        display_name: created.dictionary.display_name,
      });
      form.setValues(EMPTY_DICTIONARY_FORM);
      form.resetDirty();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={close}
      title={t("dictionaries.create.title")}
      size="lg"
    >
      <form noValidate onSubmit={form.onSubmit((values) => void submit(values))}>
        <Stack>
          <DictionaryFormFields form={form} editable nameEditable />
          {error ? (
            <Text size="sm" c="red">
              {error}
            </Text>
          ) : null}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={busy}>
              {t("dictionaries.create.submit")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
