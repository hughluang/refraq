"use client";

import { MultiSelect, Stack, TagsInput, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import { userAttributeLabel } from "@/features/entities/entityPresentation";
import type { SubjectAttribute, SubjectValues } from "@/features/subjects/types";
import type { UserRow } from "@/features/users/types";

type Props = {
  definitions: SubjectAttribute[];
  drafts: Record<string, string[]>;
  users: UserRow[];
  editable: boolean;
  onChange: (key: string, texts: string[]) => void;
};

function userOption(user: UserRow) {
  return {
    value: user.id,
    label: userAttributeLabel({
      userId: user.id,
      account: user.account,
      displayName: user.display_name,
    }),
  };
}

export function SubjectValuesEditor({
  definitions,
  drafts,
  users,
  editable,
  onChange,
}: Props) {
  const t = useTranslate();
  if (definitions.length === 0) {
    return <Text size="sm">{t("subjectAttributes.values.empty")}</Text>;
  }
  const options = users.map(userOption);
  return (
    <Stack gap="sm">
      {definitions.map((definition) => {
        const texts = drafts[definition.key] ?? [];
        const label = definition.name;
        const description = definition.key;
        if (definition.value_type === "user") {
          if (definition.multi_value) {
            if (!editable) {
              return (
                <FieldDisplay
                  key={definition.id}
                  label={label}
                  description={description}
                  value={texts
                    .map(
                      (id) =>
                        options.find((option) => option.value === id)?.label ??
                        id,
                    )
                    .join(", ")}
                />
              );
            }
            return (
              <MultiSelect
                key={definition.id}
                label={label}
                description={description}
                data={options}
                value={texts}
                onChange={(next) => onChange(definition.key, next)}
                searchable
              />
            );
          }
          return (
            <SelectField
              key={definition.id}
              editable={editable}
              label={label}
              description={description}
              data={options}
              value={texts[0] ?? null}
              clearable
              searchable
              onChange={(next) =>
                onChange(definition.key, next ? [next] : [])
              }
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
