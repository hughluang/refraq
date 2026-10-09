"use client";

import { Button, CloseButton, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import {
  emptyRow,
  fieldsFromSchema,
  type FieldSpec,
  type SchemaObject,
} from "@/features/channels/configSchemaForm";
import { EntityAttributeSelect } from "@/features/channels/EntityAttributeSelect";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { nodeTypeSummary } from "@/features/channels/nodeTypeCopy";
import type { NodeTypeSpec } from "@/features/channels/types";
import { TargetEntityField } from "@/features/entities/TargetEntityField";

type Props = {
  nodeId: string;
  data: FlowNodeData;
  spec: NodeTypeSpec | null;
  schema: SchemaObject | null;
  editable: boolean;
  problemLines?: readonly string[];
  onClose: () => void;
  onChange: (nodeId: string, data: FlowNodeData) => void;
};

export function NodeConfigPanel({
  nodeId,
  data,
  spec,
  schema,
  editable,
  problemLines = [],
  onClose,
  onChange,
}: Props) {
  const t = useTranslate();
  const summary = spec ? nodeTypeSummary(t, spec) : "";
  const fields = schema ? fieldsFromSchema(schema) : [];
  const entityId = typeof data.config.entity_id === "string" ? data.config.entity_id : "";

  const update = (patch: Partial<FlowNodeData>) => {
    onChange(nodeId, { ...data, ...patch });
  };

  const setConfig = (key: string, value: unknown) => {
    update({ config: { ...data.config, [key]: value } });
  };

  return (
    <>
      <div className="channel-node-config__header">
        <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <TextField
              editable={editable}
              aria-label={t("channels.node.name")}
              placeholder={t("channels.node.name")}
              value={data.name}
              onChange={(event) => update({ name: event.currentTarget.value })}
            />
            {summary ? (
              <Text size="xs" c="dimmed">
                {summary}
              </Text>
            ) : null}
          </Stack>
          <CloseButton size="sm" aria-label={t("channels.node.close")} onClick={onClose} />
        </Group>
      </div>
      <div className="channel-node-config__body">
        <Stack gap="sm">
          {problemLines.map((line, index) => (
            <Text key={`${index}-${line}`} c="red" size="sm">
              {line}
            </Text>
          ))}
          <SelectField
            editable={editable}
            label={t("channels.node.onError")}
            data={[
              { value: "stop", label: t("channels.node.onError.stop") },
              { value: "continue", label: t("channels.node.onError.continue") },
              { value: "error_output", label: t("channels.node.onError.error_output") },
            ]}
            value={data.onError}
            onChange={(next) => {
              if (next === "stop" || next === "continue" || next === "error_output") {
                update({ onError: next });
              }
            }}
            allowDeselect={false}
          />
          {fields.map((field) => (
            <ConfigField
              key={field.key}
              field={field}
              value={data.config[field.key]}
              entityId={entityId}
              editable={editable}
              onChange={(value) => setConfig(field.key, value)}
            />
          ))}
        </Stack>
      </div>
    </>
  );
}

function ConfigField({
  field,
  value,
  entityId,
  editable,
  onChange,
}: {
  field: FieldSpec;
  value: unknown;
  entityId: string;
  editable: boolean;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const label = t(`channels.config.fields.${field.key}`);
  if (field.kind === "entity") {
    return (
      <TargetEntityField
        label={label}
        value={typeof value === "string" ? value : ""}
        selfEntityId={null}
        selfName=""
        selfTableName=""
        includeSelf={false}
        editable={editable}
        cachedName=""
        cachedTableName=""
        onChange={(next) => onChange(next.target_entity_id)}
      />
    );
  }
  if (field.kind === "attribute") {
    return (
      <EntityAttributeSelect
        entityId={entityId}
        label={label}
        editable={editable}
        allowEmpty={field.allowEmpty}
        value={typeof value === "string" ? value : null}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "enum") {
    const options = field.options.map((option) => ({
      value: option,
      label: optionLabel(t, field.key, option),
    }));
    return (
      <SelectField
        editable={editable}
        label={label}
        data={options}
        value={typeof value === "string" ? value : null}
        onChange={(next) => onChange(next ?? "")}
        allowDeselect={false}
      />
    );
  }
  if (field.kind === "objectList") {
    const rows = Array.isArray(value) ? value.filter(isRecord) : [];
    return (
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={500}>
            {label}
          </Text>
          {editable ? (
            <Button
              size="xs"
              variant="light"
              onClick={() => onChange([...rows, emptyRow(field.fields)])}
            >
              {t("channels.config.addItem")}
            </Button>
          ) : null}
        </Group>
        {rows.map((row, index) => (
          <Stack key={`${field.key}-${index}`} gap="xs">
            {field.fields.map((child) => (
              <ConfigField
                key={child.key}
                field={child}
                value={row[child.key]}
                entityId={entityId}
                editable={editable}
                onChange={(next) => {
                  const copy = rows.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, [child.key]: next } : item,
                  );
                  onChange(copy);
                }}
              />
            ))}
            {editable ? (
              <Button
                size="xs"
                variant="subtle"
                color="red"
                onClick={() => onChange(rows.filter((_, itemIndex) => itemIndex !== index))}
              >
                {t("channels.config.removeItem")}
              </Button>
            ) : null}
          </Stack>
        ))}
      </Stack>
    );
  }
  return (
    <TextField
      editable={editable}
      label={label}
      value={typeof value === "string" ? value : ""}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}

function optionLabel(
  t: (key: string) => string,
  field: string,
  option: string,
): string {
  const key = `channels.config.options.${field}.${option}`;
  const translated = t(key);
  return translated === key ? option : translated;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
