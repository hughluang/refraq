"use client";

import { ActionIcon, Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";
import { JsonField } from "@/components/form/JsonField";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import { CloseIcon, PlusIcon } from "@/components/icons";

export const SUBCHANNEL_PARAM_TYPES = [
  "string",
  "integer",
  "number",
  "boolean",
  "object",
  "array",
  "dataset",
] as const;

export type SubchannelParamType = (typeof SUBCHANNEL_PARAM_TYPES)[number];

export type SubchannelContractParam = {
  name: string;
  type: SubchannelParamType;
  required: boolean;
  hasDefault: boolean;
  defaultValue: unknown;
  description: string;
};

type ParamRow = SubchannelContractParam;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeParamType(raw: unknown): SubchannelParamType {
  if (
    typeof raw === "string" &&
    (SUBCHANNEL_PARAM_TYPES as readonly string[]).includes(raw)
  ) {
    return raw as SubchannelParamType;
  }
  return "string";
}

export function parseSubchannelParamRows(raw: unknown): SubchannelContractParam[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).map((item) => {
    const type = normalizeParamType(item.type);
    const required = item.required !== false;
    const hasDefault =
      !required && type !== "dataset" && Object.prototype.hasOwnProperty.call(item, "default");
    return {
      name: typeof item.name === "string" ? item.name : "",
      type,
      required,
      hasDefault,
      defaultValue: hasDefault ? item.default : undefined,
      description: typeof item.description === "string" ? item.description : "",
    };
  });
}

function serializeRow(row: ParamRow): Record<string, unknown> {
  const out: Record<string, unknown> = {
    name: row.name,
    type: row.type,
    required: row.required,
  };
  if (!row.required && row.type !== "dataset" && row.hasDefault) {
    out.default = row.defaultValue;
  }
  if (row.description.trim() !== "") {
    out.description = row.description;
  }
  return out;
}

function initialDefaultFor(type: Exclude<SubchannelParamType, "dataset">): unknown {
  switch (type) {
    case "string":
      return "";
    case "integer":
    case "number":
      return 0;
    case "boolean":
      return false;
    case "object":
      return {};
    case "array":
      return [];
  }
}

export function SubchannelTriggerFields({
  config,
  editable,
  notes = [],
  onChange,
}: {
  config: Record<string, unknown>;
  editable: boolean;
  notes?: readonly FieldNote[];
  onChange: (config: Record<string, unknown>) => void;
}) {
  const t = useTranslate();
  const rows = parseSubchannelParamRows(config.input);
  const sampleInput = isRecord(config.sample_input) ? config.sample_input : {};

  const writeRows = (nextRows: ParamRow[]) => {
    onChange({
      ...config,
      input: nextRows.map(serializeRow),
    });
  };

  const patchRow = (index: number, patch: Partial<ParamRow>) => {
    const next = rows.map((row, idx) => {
      if (idx !== index) return row;
      const merged = { ...row, ...patch };
      if (merged.required || merged.type === "dataset") {
        merged.hasDefault = false;
        merged.defaultValue = undefined;
      } else if (patch.type && patch.type !== row.type && merged.hasDefault) {
        merged.defaultValue = initialDefaultFor(
          merged.type as Exclude<SubchannelParamType, "dataset">
        );
      }
      return merged;
    });
    writeRows(next);
  };

  const typeOptions = SUBCHANNEL_PARAM_TYPES.map((value) => ({
    value,
    label: t(`channels.config.options.subchannel_type.${value}`, { defaultValue: value }),
  }));

  return (
    <Stack gap="md">
      <Stack gap="xs" role="group" aria-label={t("channels.config.fields.trigger.subchannel.input")}>
        <Group justify="space-between" align="center">
          <Group gap={6} align="center">
            <Text size="sm" fw={500}>
              {t("channels.config.fields.trigger.subchannel.input")}
            </Text>
            {notes.length > 0 ? (
              <FieldMarks
                label={t("channels.config.fields.trigger.subchannel.input")}
                notes={notes}
              />
            ) : null}
          </Group>
          {editable ? (
            <Button
              type="button"
              size="compact-xs"
              variant="light"
              disabled={rows.length >= 100}
              leftSection={<PlusIcon size={14} />}
              onClick={() =>
                writeRows([
                  ...rows,
                  {
                    name: "",
                    type: "string",
                    required: true,
                    hasDefault: false,
                    defaultValue: undefined,
                    description: "",
                  },
                ])
              }
            >
              {t("channels.config.subchannel.addParameter")}
            </Button>
          ) : null}
        </Group>
        <Text size="xs" c="dimmed">
          {t("channels.config.fields.trigger.subchannel.input.description")}
        </Text>
        {rows.length === 0 ? (
          <Text size="xs" c="dimmed">
            {t("channels.config.subchannel.noParameters")}
          </Text>
        ) : (
          <Stack gap="sm">
            {rows.map((row, index) => (
              <Stack
                key={index}
                gap="xs"
                p="xs"
                style={{
                  border: "1px solid var(--mantine-color-default-border)",
                  borderRadius: "var(--mantine-radius-sm)",
                }}
              >
                <Group gap="xs" align="flex-end" wrap="nowrap">
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <TextField
                      editable={editable}
                      label={t("channels.config.fields.trigger.subchannel.param.name")}
                      value={row.name}
                      onChange={(event) =>
                        patchRow(index, { name: event.currentTarget.value })
                      }
                    />
                  </div>
                  <div style={{ width: 150, flex: "none" }}>
                    <SelectField
                      editable={editable}
                      label={t("channels.config.fields.trigger.subchannel.param.type")}
                      data={typeOptions}
                      value={row.type}
                      allowDeselect={false}
                      onChange={(next) => {
                        if (next) patchRow(index, { type: normalizeParamType(next) });
                      }}
                    />
                  </div>
                  {editable ? (
                    <ActionIcon
                      type="button"
                      variant="subtle"
                      color="gray"
                      aria-label={t("channels.config.subchannel.removeParameter")}
                      onClick={() =>
                        writeRows(rows.filter((_, candidate) => candidate !== index))
                      }
                    >
                      <CloseIcon size={14} />
                    </ActionIcon>
                  ) : null}
                </Group>
                <Group gap="md" align="center">
                  <SwitchField
                    editable={editable}
                    label={t("channels.config.fields.trigger.subchannel.param.required")}
                    checked={row.required}
                    onChange={(event) =>
                      patchRow(index, { required: event.currentTarget.checked })
                    }
                  />
                  {!row.required && row.type !== "dataset" ? (
                    <SwitchField
                      editable={editable}
                      label={t("channels.config.fields.trigger.subchannel.param.hasDefault")}
                      checked={row.hasDefault}
                      onChange={(event) => {
                        const checked = event.currentTarget.checked;
                        patchRow(index, {
                          hasDefault: checked,
                          defaultValue: checked
                            ? initialDefaultFor(
                                row.type as Exclude<SubchannelParamType, "dataset">
                              )
                            : undefined,
                        });
                      }}
                    />
                  ) : null}
                </Group>
                {!row.required && row.type !== "dataset" && row.hasDefault ? (
                  row.type === "string" ? (
                    <TextField
                      editable={editable}
                      label={t("channels.config.fields.trigger.subchannel.param.default")}
                      value={typeof row.defaultValue === "string" ? row.defaultValue : ""}
                      onChange={(event) =>
                        patchRow(index, { defaultValue: event.currentTarget.value })
                      }
                    />
                  ) : row.type === "boolean" ? (
                    <SwitchField
                      editable={editable}
                      label={t("channels.config.fields.trigger.subchannel.param.default")}
                      checked={Boolean(row.defaultValue)}
                      onChange={(event) =>
                        patchRow(index, { defaultValue: event.currentTarget.checked })
                      }
                    />
                  ) : (
                    <JsonField
                      editable={editable}
                      label={t("channels.config.fields.trigger.subchannel.param.default")}
                      value={row.defaultValue}
                      onChange={(next) => patchRow(index, { defaultValue: next })}
                    />
                  )
                ) : null}
                <TextField
                  editable={editable}
                  label={t("channels.config.fields.trigger.subchannel.param.description")}
                  value={row.description}
                  onChange={(event) =>
                    patchRow(index, { description: event.currentTarget.value })
                  }
                />
              </Stack>
            ))}
          </Stack>
        )}
      </Stack>
      <JsonField
        editable={editable}
        label={t("channels.config.fields.trigger.subchannel.sample_input")}
        description={t("channels.config.fields.trigger.subchannel.sample_input.description")}
        value={sampleInput}
        accept={isRecord}
        onChange={(next) =>
          onChange({
            ...config,
            sample_input: next as Record<string, unknown>,
          })
        }
      />
    </Stack>
  );
}
