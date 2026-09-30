"use client";

import { Button, Group, Stack, Table, Text } from "@mantine/core";
import type { UseFormReturnType } from "@mantine/form";
import { useTranslate } from "@refinedev/core";

import { SwitchField } from "@/components/form/SwitchField";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { EMPTY_DICTIONARY_ENTRY } from "@/features/dictionaries/dictionaryForm";
import type { DictionaryFormValues } from "@/features/dictionaries/types";

type Props = {
  form: UseFormReturnType<DictionaryFormValues>;
  editable: boolean;
  nameEditable: boolean;
};

export function DictionaryFormFields({ form, editable, nameEditable }: Props) {
  const t = useTranslate();
  const entries = form.values.entries;

  return (
    <Stack>
      <TextField
        editable={nameEditable}
        required
        label={t("dictionaries.fields.name")}
        {...form.getInputProps("name")}
      />
      <TextField
        editable={editable}
        required
        label={t("dictionaries.fields.displayName")}
        {...form.getInputProps("display_name")}
      />
      <TextareaField
        editable={editable}
        minRows={2}
        label={t("dictionaries.fields.description")}
        {...form.getInputProps("description")}
      />
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          {t("dictionaries.fields.entries")}
        </Text>
        {form.errors.entries ? (
          <Text size="sm" c="red">
            {form.errors.entries}
          </Text>
        ) : null}
        <Table horizontalSpacing="sm" verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("dictionaries.fields.code")}</Table.Th>
              <Table.Th>{t("dictionaries.fields.label")}</Table.Th>
              <Table.Th>{t("dictionaries.fields.active")}</Table.Th>
              {editable ? <Table.Th /> : null}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {entries.map((entry, index) => (
              <Table.Tr key={index}>
                <Table.Td>
                  <TextField
                    editable={editable}
                    required
                    aria-label={t("dictionaries.fields.code")}
                    {...form.getInputProps(`entries.${index}.code`)}
                  />
                </Table.Td>
                <Table.Td>
                  <TextField
                    editable={editable}
                    aria-label={t("dictionaries.fields.label")}
                    {...form.getInputProps(`entries.${index}.label`)}
                  />
                </Table.Td>
                <Table.Td>
                  <SwitchField
                    editable={editable}
                    aria-label={t("dictionaries.fields.active")}
                    checked={entry.active}
                    onChange={(event) =>
                      form.setFieldValue(
                        `entries.${index}.active`,
                        event.currentTarget.checked,
                      )
                    }
                  />
                </Table.Td>
                {editable ? (
                  <Table.Td>
                    <Button
                      type="button"
                      variant="subtle"
                      color="red"
                      size="xs"
                      onClick={() => form.removeListItem("entries", index)}
                    >
                      {t("dictionaries.entries.remove")}
                    </Button>
                  </Table.Td>
                ) : null}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {editable ? (
          <Group>
            <Button
              type="button"
              variant="default"
              size="xs"
              onClick={() =>
                form.insertListItem("entries", { ...EMPTY_DICTIONARY_ENTRY })
              }
            >
              {t("dictionaries.entries.add")}
            </Button>
          </Group>
        ) : null}
      </Stack>
    </Stack>
  );
}
