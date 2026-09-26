"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { CSSProperties } from "react";

import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
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
  editable: boolean;
};

/** Column flex basis. Validation copy renders under the row, not inside these columns. */
const NAME_COL: CSSProperties = { flex: "1 1 10rem", minWidth: 0 };
const TYPE_COL: CSSProperties = { flex: "1 1 9rem", minWidth: 0 };
const DESCRIPTION_COL: CSSProperties = { flex: "2 1 12rem", minWidth: 0 };
/** Shared width so flag headers line up with the switches under them. */
const FLAG_COL: CSSProperties = { flex: "0 0 5.5rem" };

function splitFieldError(props: object): {
  message: string | null;
  inputProps: object;
} {
  const record = props as { error?: unknown };
  const message = typeof record.error === "string" && record.error ? record.error : null;
  const { error: _error, ...inputProps } = record;
  return { message, inputProps };
}

function ColumnHeading({
  label,
  style,
}: {
  label: string;
  style: CSSProperties;
}) {
  return (
    <Text component="div" size="sm" fw={500} style={style}>
      {label}
    </Text>
  );
}

export function AttributeEditor({ form, editable }: Props) {
  const t = useTranslate();
  const attributes = form.values.attributes;
  const nameLabel = t("entities.fields.attributeName");
  const typeLabel = t("entities.fields.normalizedType");
  const nullableLabel = t("entities.fields.nullable");
  const uniqueLabel = t("entities.fields.unique");
  const indexedLabel = t("entities.fields.indexed");
  const descriptionLabel = t("entities.fields.attributeDescription");

  return (
    <Stack gap="sm">
      <Group align="flex-start" wrap="wrap" gap="xs">
        <ColumnHeading label={nameLabel} style={NAME_COL} />
        <ColumnHeading label={typeLabel} style={TYPE_COL} />
        <ColumnHeading label={nullableLabel} style={FLAG_COL} />
        <ColumnHeading label={uniqueLabel} style={FLAG_COL} />
        <ColumnHeading label={indexedLabel} style={FLAG_COL} />
        <ColumnHeading label={descriptionLabel} style={DESCRIPTION_COL} />
        {editable ? (
          <Button
            size="xs"
            variant="subtle"
            aria-hidden
            tabIndex={-1}
            style={{ visibility: "hidden" }}
          >
            {t("actions.delete")}
          </Button>
        ) : null}
      </Group>
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
              <TextField
                editable={editable}
                style={NAME_COL}
                {...nameField.inputProps}
                aria-label={nameLabel}
                error={editable && nameField.message != null}
              />
              <SelectField
                data={NORMALIZED_TYPES}
                allowDeselect={false}
                editable={editable}
                style={TYPE_COL}
                {...typeField.inputProps}
                aria-label={typeLabel}
                error={editable && typeField.message != null}
              />
              <SwitchField
                editable={editable}
                style={FLAG_COL}
                {...form.getInputProps(`attributes.${index}.nullable`, {
                  type: "checkbox",
                })}
                aria-label={nullableLabel}
              />
              <SwitchField
                editable={editable}
                style={FLAG_COL}
                {...form.getInputProps(`attributes.${index}.unique`, {
                  type: "checkbox",
                })}
                aria-label={uniqueLabel}
              />
              <SwitchField
                editable={editable}
                style={FLAG_COL}
                {...form.getInputProps(`attributes.${index}.indexed`, {
                  type: "checkbox",
                })}
                aria-label={indexedLabel}
              />
              <TextField
                editable={editable}
                style={DESCRIPTION_COL}
                {...descriptionField.inputProps}
                aria-label={descriptionLabel}
                error={editable && descriptionField.message != null}
              />
              {editable ? (
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  onClick={() => form.removeListItem("attributes", index)}
                >
                  {t("actions.delete")}
                </Button>
              ) : null}
            </Group>
            {editable && messages.length > 0 ? (
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
      {editable ? (
        <Button
          size="xs"
          variant="light"
          onClick={() => form.insertListItem("attributes", { ...EMPTY_ATTRIBUTE })}
        >
          {t("entities.attributes.add")}
        </Button>
      ) : null}
    </Stack>
  );
}
