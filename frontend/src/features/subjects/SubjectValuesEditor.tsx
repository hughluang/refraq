"use client";

import { Stack, TagsInput, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";
import { RecordMultiPicker, RecordPicker } from "@/components/form/RecordPicker";
import { userRecordAdapter } from "@/components/form/recordPickerAdapters";
import { TextField } from "@/components/form/TextField";
import type { SubjectAttribute, SubjectValues } from "@/features/subjects/types";

type Props = {
  definitions: SubjectAttribute[];
  drafts: Record<string, string[]>;
  editable: boolean;
  onChange: (key: string, texts: string[]) => void;
};

export function SubjectValuesEditor({
  definitions,
  drafts,
  editable,
  onChange,
}: Props) {
  const t = useTranslate();
  if (definitions.length === 0) {
    return <Text size="sm">{t("subjectAttributes.values.empty")}</Text>;
  }
  const users = userRecordAdapter();
  return (
    <Stack gap="sm">
      {definitions.map((definition) => {
        const texts = drafts[definition.key] ?? [];
        const label = definition.name;
        const description = definition.key;
        if (definition.value_type === "user") {
          if (definition.multi_value) {
            return (
              <RecordMultiPicker
                key={definition.id}
                editable={editable}
                label={label}
                description={description}
                adapter={users}
                value={texts}
                onChange={(next) => onChange(definition.key, next)}
              />
            );
          }
          return (
            <RecordPicker
              key={definition.id}
              editable={editable}
              label={label}
              description={description}
              adapter={users}
              value={texts[0] ?? null}
              clearable
              onChange={(next) => onChange(definition.key, next ? [next] : [])}
            />
          );
        }
        if (definition.multi_value) {
          if (!editable) {
            return (
              <FieldDisplay
                key={definition.id}
                label={label}
                description={description}
                value={texts.join(", ")}
              />
            );
          }
          return (
            <TagsInput
              key={definition.id}
              label={label}
              description={description}
              value={texts}
              onChange={(next) => onChange(definition.key, next)}
            />
          );
        }
        return (
          <TextField
            key={definition.id}
            editable={editable}
            label={label}
            description={description}
            value={texts[0] ?? ""}
            onChange={(event) =>
              onChange(
                definition.key,
                event.currentTarget.value ? [event.currentTarget.value] : [],
              )
            }
          />
        );
      })}
    </Stack>
  );
}

export function formatSubjectValues(values: SubjectValues): string {
  const keys = Object.keys(values).sort();
  if (keys.length === 0) return "";
  return keys
    .map((key) => `${key}: ${(values[key] ?? []).map(String).join(", ")}`)
    .join("\n");
}
