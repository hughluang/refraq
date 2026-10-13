"use client";

import { ActionIcon, Button, CloseButton, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldDisclosureContext, FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import { ScheduledCadenceFields } from "@/features/channels/ScheduledCadenceFields";
import { SqlSourceField } from "@/features/channels/SqlSourceField";
import {
  emptyRow,
  fieldsFromSchema,
  type FieldSpec,
  type SchemaObject,
} from "@/features/channels/configSchemaForm";
import { EntityAttributeSelect } from "@/features/channels/EntityAttributeSelect";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { resolvedMatchKeyName } from "@/features/channels/matchKeyName";
import { nodeTypeSummary } from "@/features/channels/nodeTypeCopy";
import {
  fieldMessages,
  formatGraphProblem,
  problemIdentity,
  type FieldMessage,
  type ProblemGraph,
} from "@/features/channels/problemLabel";
import type { GraphProblem } from "@/features/channels/types";
import { TemplateField } from "@/features/channels/TemplateField";
import {
  attributeValueSchema,
  type UpstreamOutput,
} from "@/features/channels/templateLogic";
import type { NodeTypeSpec } from "@/features/channels/types";
import { useEntityHeadAttributes } from "@/features/channels/useEntityHeadAttributes";
import type { EntityAttribute } from "@/features/entities/types";
import { TargetEntityField } from "@/features/entities/TargetEntityField";

type Props = {
  nodeId: string;
  data: FlowNodeData;
  spec: NodeTypeSpec | null;
  schema: SchemaObject | null;
  editable: boolean;
  revealKey?: string | null;
  problems?: readonly GraphProblem[];
  graph?: ProblemGraph;
  upstream?: readonly UpstreamOutput[];
  onClose: () => void;
  onChange: (nodeId: string, data: FlowNodeData) => void;
};

const EMPTY_GRAPH: ProblemGraph = { nodes: [], edges: [] };

type HeadState = {
  attributes: readonly EntityAttribute[];
  failed: boolean;
  ready: boolean;
};

export function NodeConfigPanel({
  nodeId,
  data,
  spec,
  schema,
  editable,
  revealKey = null,
  problems = [],
  graph = EMPTY_GRAPH,
  upstream = [],
  onClose,
  onChange,
}: Props) {
  const t = useTranslate();
  const summary = spec ? nodeTypeSummary(t, spec) : "";
  const fields = (schema ? fieldsFromSchema(schema) : []).filter((field) =>
    data.nodeType === "trigger.scheduled"
      ? !["cron", "interval_seconds", "start_at"].includes(field.key)
      : true,
  );
  const entityId = typeof data.config.entity_id === "string" ? data.config.entity_id : "";
  const head = useEntityHeadAttributes(entityId);
  const attached = new Set<string>(fields.map((field) => field.key));
  if (data.nodeType === "trigger.scheduled") {
    attached.add("cron");
    attached.add("interval_seconds");
    attached.add("start_at");
  }
  if (data.config.mode === "delete") attached.delete("mapping");
  const headerProblems = problems.filter((problem) => {
    const headKey = problem.path[0];
    return typeof headKey !== "string" || !attached.has(headKey);
  });
  const headerNotes = toNotes(
    headerProblems.map((problem) => ({
      text: formatGraphProblem(t, problem, graph, { nodeName: false }),
      severity: problem.severity === "warning" ? ("warning" as const) : ("error" as const),
    })),
  );
  const headerSignal = headerProblems.some((problem) => problemIdentity(problem) === revealKey)
    ? revealKey
    : null;

  const update = (patch: Partial<FlowNodeData>) => {
    onChange(nodeId, { ...data, ...patch });
  };

  const setConfig = (key: string, value: unknown) => {
    if (value === undefined) {
      const next = { ...data.config };
      delete next[key];
      update({ config: next });
      return;
    }
    update({ config: { ...data.config, [key]: value } });
  };

  return (
    <FieldDisclosureContext.Provider value="quiet">
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
            <TextField
              editable={editable}
              label={t("channels.node.ref")}
              value={data.ref}
              onChange={(event) => update({ ref: event.currentTarget.value })}
            />
            {summary ? (
              <Text size="xs" c="dimmed">
                {summary}
              </Text>
            ) : null}
          </Stack>
          <Group gap={4} wrap="nowrap" align="flex-start">
            {headerNotes.length > 0 ? (
              <FieldMarks
                label={data.name}
                notes={headerNotes}
                openSignal={headerSignal}
              />
            ) : null}
            <CloseButton size="sm" aria-label={t("channels.node.close")} onClick={onClose} />
          </Group>
        </Group>
      </div>
      <div className="channel-node-config__body">
        <Stack gap="sm">
          <SelectField
            editable={editable}
            label={t("channels.node.onError")}
            data={[{ value: "stop", label: t("channels.node.onError.stop") }]}
            value={data.onError}
            onChange={(next) => {
              if (next === "stop" || next === "continue" || next === "error_output") {
                update({ onError: next });
              }
            }}
            allowDeselect={false}
          />
          {data.nodeType === "trigger.scheduled" ? (
            <ScheduledCadenceFields
              config={data.config}
              editable={editable}
              notes={{
                cron: toNotes(fieldMessages(t, problems, "cron", graph)),
                interval_seconds: toNotes(fieldMessages(t, problems, "interval_seconds", graph)),
                start_at: toNotes(fieldMessages(t, problems, "start_at", graph)),
              }}
              openSignal={{
                cron: signalFor(problems, "cron", revealKey),
                interval_seconds: signalFor(problems, "interval_seconds", revealKey),
                start_at: signalFor(problems, "start_at", revealKey),
              }}
              onChange={(config) => update({ config })}
            />
          ) : null}
          {fields.map((field) => (
            <ConfigField
              key={field.key}
              field={field}
              value={data.config[field.key]}
              entityId={entityId}
              editable={editable}
              head={head}
              config={data.config}
              scope={data.config}
              upstream={upstream}
              messages={fieldMessages(t, problems, field.key, graph)}
              openSignal={signalFor(problems, field.key, revealKey)}
              onChange={(value) => setConfig(field.key, value)}
            />
          ))}
        </Stack>
      </div>
    </FieldDisclosureContext.Provider>
  );
}

function ConfigField({
  field,
  value,
  entityId,
  editable,
  labeled = true,
  exclude = [],
  head,
  config,
  scope,
  upstream = [],
  messages = [],
  openSignal = null,
  onChange,
}: {
  field: FieldSpec;
  value: unknown;
  entityId: string;
  editable: boolean;
  labeled?: boolean;
  exclude?: readonly string[];
  head: HeadState;
  config: Record<string, unknown>;
  scope: Record<string, unknown>;
  upstream?: readonly UpstreamOutput[];
  messages?: readonly FieldMessage[];
  openSignal?: string | null;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const caption = t(`channels.config.fields.${field.key}`);
  const labelProps = labeled ? { label: caption } : { "aria-label": caption };
  const notes = toNotes(messages);
  const bare = !labeled;
  if (field.kind === "sql_source") {
    return (
      <SqlSourceField
        label={caption}
        description={field.description}
        value={value}
        editable={editable}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "entity") {
    return (
      <TargetEntityField
        label={caption}
        value={typeof value === "string" ? value : ""}
        selfEntityId={null}
        selfName=""
        selfTableName=""
        includeSelf={false}
        editable={editable}
        cachedName=""
        cachedTableName=""
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={(next) => onChange(next.target_entity_id)}
      />
    );
  }
  if (field.kind === "attribute") {
    return (
      <EntityAttributeSelect
        entityId={entityId}
        label={labeled ? caption : undefined}
        aria-label={labeled ? undefined : caption}
        editable={editable}
        allowEmpty={field.allowEmpty}
        exclude={exclude}
        attributes={head.attributes}
        failed={labeled ? head.failed : false}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        size={labeled ? undefined : "xs"}
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
        {...labelProps}
        data={options}
        value={typeof value === "string" ? value : null}
        size={labeled ? undefined : "xs"}
        w={labeled ? undefined : "100%"}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={(next) => onChange(next ?? "")}
        allowDeselect={false}
      />
    );
  }
  if (field.kind === "objectList") {
    return (
      <ObjectListEditor
        field={field}
        value={value}
        entityId={entityId}
        editable={editable}
        head={head}
        config={config}
        upstream={upstream}
        notes={notes}
        openSignal={openSignal}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "integer") {
    return (
      <NumberField
        editable={editable}
        {...labelProps}
        description={field.description}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        min={field.minimum}
        max={field.maximum}
        value={typeof value === "number" ? value : ""}
        onChange={(next) => {
          if (typeof next === "number") onChange(next);
          else if (field.nullable) onChange(null);
          else onChange(undefined);
        }}
      />
    );
  }
  if (field.kind === "template") {
    const valueSchema = "from" in field.valueSchema ? attributeSchema(scope, head) : field.valueSchema;
    return (
      <TemplateField
        label={labeled ? caption : undefined}
        ariaLabel={labeled ? undefined : caption}
        description={field.description}
        valueSchema={valueSchema}
        value={typeof value === "string" ? value : ""}
        editable={editable}
        upstream={upstream}
        messages={messages}
        openSignal={openSignal}
        onChange={onChange}
      />
    );
  }
  return (
    <TextField
      editable={editable}
      {...labelProps}
      value={typeof value === "string" ? value : ""}
      size={labeled ? undefined : "xs"}
      w={labeled ? undefined : "100%"}
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}

function ObjectListEditor({
  field,
  value,
  entityId,
  editable,
  head,
  config,
  upstream = [],
  notes,
  openSignal = null,
  onChange,
}: {
  field: Extract<FieldSpec, { kind: "objectList" }>;
  value: unknown;
  entityId: string;
  editable: boolean;
  head: HeadState;
  config: Record<string, unknown>;
  upstream?: readonly UpstreamOutput[];
  notes: readonly FieldNote[];
  openSignal?: string | null;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const label = t(`channels.config.fields.${field.key}`);
  const rows = Array.isArray(value) ? value.filter(isRecord) : [];
  if (field.key === "mapping" && config.mode === "delete") return null;

  const taken = attributeNames(rows);
  const addBlocked =
    field.key === "mapping" &&
    head.ready &&
    !head.attributes.some((attribute) => !taken.has(attribute.name));
  const matchName =
    field.key === "mapping" && head.ready
      ? resolvedMatchKeyName(config.match_key, head.attributes)
      : null;
  const showMatchHint = matchName != null && !taken.has(matchName);
  const columnClass =
    field.fields.length === 3 ? "channel-config-grid--3" : "channel-config-grid--2";

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap={4} wrap="nowrap">
          <Text size="sm" fw={500}>
            {label}
          </Text>
          <FieldMarks
            label={label}
            description={field.description}
            notes={[
              ...notes,
              ...(head.failed && field.fields.some((child) => child.kind === "attribute")
                ? [{ text: t("channels.config.attributeLoadFailed"), tone: "error" as const }]
                : []),
              ...(showMatchHint
                ? [
                    {
                      text: t("channels.config.mapping.matchKeyMissing", { name: matchName }),
                      tone: "error" as const,
                    },
                  ]
                : []),
            ]}
            openSignal={openSignal}
          />
        </Group>
        {editable ? (
          <Button
            type="button"
            size="xs"
            variant="light"
            disabled={addBlocked}
            onClick={() => onChange([...rows, emptyRow(field.fields)])}
          >
            {t("channels.config.addItem")}
          </Button>
        ) : null}
      </Group>
      {rows.length > 0 ? (
        <div
          className={[
            "channel-config-grid",
            columnClass,
            editable ? "channel-config-grid--actions" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {field.fields.map((child) => (
            <Text key={child.key} size="xs" fw={500} c="dimmed">
              {t(`channels.config.fields.${child.key}`)}
            </Text>
          ))}
          {editable ? <span /> : null}
          {rows.map((row, index) => (
            <ListRow
              key={`${field.key}-${index}`}
              field={field}
              row={row}
              index={index}
              rows={rows}
              entityId={entityId}
              editable={editable}
              head={head}
              config={config}
              upstream={upstream}
              onChange={onChange}
            />
          ))}
        </div>
      ) : null}
    </Stack>
  );
}

function ListRow({
  field,
  row,
  index,
  rows,
  entityId,
  editable,
  head,
  config,
  upstream = [],
  onChange,
}: {
  field: Extract<FieldSpec, { kind: "objectList" }>;
  row: Record<string, unknown>;
  index: number;
  rows: Record<string, unknown>[];
  entityId: string;
  editable: boolean;
  head: HeadState;
  config: Record<string, unknown>;
  upstream?: readonly UpstreamOutput[];
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const replace = (key: string, next: unknown) => {
    onChange(
      rows.map((item, itemIndex) => {
        if (itemIndex !== index) return item;
        if (next === undefined) {
          const copy = { ...item };
          delete copy[key];
          return copy;
        }
        return { ...item, [key]: next };
      }),
    );
  };
  return (
    <>
      {field.fields.map((child) => (
        <div key={child.key} className="channel-config-grid__cell">
          <ConfigField
            field={child}
            value={row[child.key]}
            entityId={entityId}
            editable={editable}
            labeled={false}
            exclude={
              field.key === "mapping" && child.kind === "attribute"
                ? otherAttributeNames(rows, index)
                : []
            }
            head={head}
            config={config}
            scope={row}
            upstream={upstream}
            onChange={(next) => replace(child.key, next)}
          />
        </div>
      ))}
      {editable ? (
        <ActionIcon
          variant="subtle"
          color="red"
          size="sm"
          aria-label={t("channels.config.removeItem")}
          onClick={() => onChange(rows.filter((_, itemIndex) => itemIndex !== index))}
        >
          ×
        </ActionIcon>
      ) : null}
    </>
  );
}

function attributeNames(rows: readonly Record<string, unknown>[]): Set<string> {
  const names = new Set<string>();
  for (const row of rows) {
    const name = row.attribute;
    if (typeof name === "string" && name !== "") names.add(name);
  }
  return names;
}

function otherAttributeNames(
  rows: readonly Record<string, unknown>[],
  index: number,
): string[] {
  const names: string[] = [];
  rows.forEach((row, rowIndex) => {
    if (rowIndex === index) return;
    const name = row.attribute;
    if (typeof name === "string" && name !== "") names.push(name);
  });
  return names;
}

function toNotes(messages: readonly FieldMessage[]): FieldNote[] {
  return messages.map((message) => ({
    text: message.text,
    tone: message.severity,
  }));
}

function signalFor(
  problems: readonly GraphProblem[],
  fieldKey: string,
  revealKey: string | null,
): string | null {
  if (!revealKey) return null;
  return problems.some(
    (problem) => problem.path[0] === fieldKey && problemIdentity(problem) === revealKey,
  )
    ? revealKey
    : null;
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

function attributeSchema(scope: Record<string, unknown>, head: HeadState) {
  const name = typeof scope.attribute === "string" ? scope.attribute : "";
  const attribute = head.attributes.find((item) => item.name === name);
  return attribute ? attributeValueSchema(attribute.type) : null;
}
