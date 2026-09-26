"use client";

import { Button, Group, Select, Stack, Switch, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { CSSProperties } from "react";

import { EMPTY_ATTRIBUTE, NORMALIZED_TYPES } from "@/features/entities/constants";
import type { AttributeDraft } from "@/features/entities/types";

export type AttributeFormApi = {
  values: { attributes: AttributeDraft[] };
  getInputProps: (
    path: string,
    options?: { type?: "checkbox" },
  ) => object;
  insertListItem: (path: string, item: AttributeDraft) => void;
  removeListItem: (path: string, index: number) => void;
};

type Props = {
  form: AttributeFormApi;
  disabled?: boolean;
};

/** Column flex basis. Validation copy renders under the row, not inside these columns. */
const NAME_COL: CSSProperties = { flex: "1 1 10rem", minWidth: 0 };
const TYPE_COL: CSSProperties = { flex: "1 1 9rem", minWidth: 0 };
const DESCRIPTION_COL: CSSProperties = { flex: "2 1 12rem", minWidth: 0 };

/** Approx. Input.Label + gap so unlabeled controls line up with labeled inputs. */
const LABEL_OFFSET_MT = "1.75rem";

function splitFieldError(props: object): {
  message: string | null;
  inputProps: object;
} {
  const record = props as { error?: unknown };
  const message = typeof record.error === "string" && record.error ? record.error : null;
  const { error: _error, ...inputProps } = record;
  return { message, inputProps };
}

export function AttributeEditor({ form, disabled = false }: Props) {
  const t = useTranslate();
  const attributes = form.values.attributes;

  return (
    <Stack gap="sm">
      {attributes.map((_, index) => {
        const nameField = splitFieldError(
          form.getInputProps(`attributes.${index}.name`),
        );
        const typeField = splitFieldError(
          form.getInputProps(`attributes.${index}.normalized_type`),
        );
        const descriptionField = splitFieldError(
          form.getInputProps(`attributes.${index}.description`),
        );
        const messages = [
          nameField.message,
          typeField.message,
          descriptionField.message,
        ].filter((message): message is string => message != null);

        return (
          <Stack key={index} gap={4}>
            <Group align="flex-start" wrap="wrap" gap="xs">
              <TextInput
                label={index === 0 ? t("entities.fields.attributeName") : undefined}
                disabled={disabled}
                style={NAME_COL}
                {...nameField.inputProps}
                error={nameField.message != null}
              />
              <Select
                label={index === 0 ? t("entities.fields.normalizedType") : undefined}
                data={NORMALIZED_TYPES}
                allowDeselect={false}
                disabled={disabled}
                style={TYPE_COL}
                {...typeField.inputProps}
                error={typeField.message != null}
              />
              <Switch
                label={t("entities.fields.nullable")}
                disabled={disabled}
                mt={index === 0 ? LABEL_OFFSET_MT : undefined}
                {...form.getInputProps(`attributes.${index}.nullable`, {
                  type: "checkbox",
                })}
              />
              <Switch
                label={t("entities.fields.unique")}
                disabled={disabled}
                mt={index === 0 ? LABEL_OFFSET_MT : undefined}
                {...form.getInputProps(`attributes.${index}.unique`, {
                  type: "checkbox",
                })}
              />
              <Switch
                label={t("entities.fields.indexed")}
                disabled={disabled}
                mt={index === 0 ? LABEL_OFFSET_MT : undefined}
                {...form.getInputProps(`attributes.${index}.indexed`, {
                  type: "checkbox",
                })}
              />
              <TextInput
                label={
                  index === 0 ? t("entities.fields.attributeDescription") : undefined
                }
                disabled={disabled}
                style={DESCRIPTION_COL}
                {...descriptionField.inputProps}
                error={descriptionField.message != null}
              />
              <Button
                size="xs"
                variant="subtle"
                color="red"
                disabled={disabled}
                mt={index === 0 ? LABEL_OFFSET_MT : undefined}
                onClick={() => form.removeListItem("attributes", index)}
              >
                {t("actions.delete")}
              </Button>
            </Group>
            {messages.length > 0 ? (
              <Stack gap={2}>
                {messages.map((message, messageIndex) => (
                  <Text key={messageIndex} c="red" size="xs">
                    {message}
                  </Text>
                ))}
              </Stack>
            ) : null}
          </Stack>
        );
      })}
      <Button
        size="xs"
        variant="light"
        disabled={disabled}
        onClick={() => form.insertListItem("attributes", { ...EMPTY_ATTRIBUTE })}
      >
        {t("entities.attributes.add")}
      </Button>
    </Stack>
  );
}
