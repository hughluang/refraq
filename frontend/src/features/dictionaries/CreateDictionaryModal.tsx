"use client";

import { Stack } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { FormDialog } from "@/components/form/FormDialog";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { DictionaryFormFields } from "@/features/dictionaries/DictionaryFormFields";
import { createDictionary } from "@/features/dictionaries/api";
import {
  EMPTY_DICTIONARY_FORM,
  dictionaryFormErrors,
  entriesFromForm,
} from "@/features/dictionaries/dictionaryForm";
import type { DictionaryFormValues } from "@/features/dictionaries/types";

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
  const form = useConsoleForm<DictionaryFormValues>({
    initialValues: EMPTY_DICTIONARY_FORM,
    validate: (values) => dictionaryFormErrors(values, t),
  });

  const close = () => {
    form.reset();
    onClose();
  };

  const submit = async (values: DictionaryFormValues) => {
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
      form.markSaved();
      form.reset();
      onClose();
    } catch (err) {
      presentSaveFailure(t, err, form.applyApiError);
    }
  };

  return (
    <FormDialog
      opened={opened}
      onClose={close}
      title={t("dictionaries.create.title")}
      size="lg"
      dirty={form.dirty}
      submitting={form.submitting}
      submitLabel={t("dictionaries.create.submit")}
      onSubmit={() => void form.submit(submit)}
    >
      <Stack>
        <DictionaryFormFields form={form} editable nameEditable />
      </Stack>
    </FormDialog>
  );
}
