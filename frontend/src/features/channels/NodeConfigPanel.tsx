"use client";

import { ActionIcon, Button, CloseButton, Group, Stack, Text } from "@mantine/core";
import { usePermissions, useTranslate } from "@refinedev/core";
import { useEffect, useRef, type ReactNode } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentNodeStatus } from "@/components/display/statusTone";
import { FieldDisclosureContext, FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";
import { JsonField } from "@/components/form/JsonField";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import { canAuthorNodeType } from "@/features/channels/nodePermission";
import { PythonCodeField } from "@/features/channels/PythonCodeField";
import { RegisteredSourceField } from "@/features/channels/RegisteredSourceField";
import { WebhookField } from "@/features/webhooks/WebhookField";
import { EmailAccountField } from "@/features/email-accounts/EmailAccountField";
import { ScheduledCadenceFields } from "@/features/channels/ScheduledCadenceFields";
import { SqlSourceField } from "@/features/channels/SqlSourceField";
import {
  emptyRow,
  fieldVisible,
  fieldsFromSchema,
  type FieldSpec,
  type SchemaObject,
} from "@/features/channels/configSchemaForm";
import { EntityAttributeSelect } from "@/features/channels/EntityAttributeSelect";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { nodeTypeLabel, nodeTypeSummary } from "@/features/channels/nodeTypeCopy";
import { NodeRegion } from "@/features/channels/NodeRegion";
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
  bindTemplatePreview,
  type ChannelTemplatePreview,
  type TemplatePreviewSource,
} from "@/features/channels/TemplateRunPreview";
import { attributeValueSchema } from "@/features/channels/templateLogic";
import type { SelfScope } from "@/features/channels/templateScope";
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
  /** Null hides the run button (browse appearance). */
  canRun: boolean | null;
  revealKey?: string | null;
  problems?: readonly GraphProblem[];
  graph?: ProblemGraph;
  scope: SelfScope;
  /** Null hides the template previews. */
  templatePreview?: ChannelTemplatePreview | null;
  /** Canvas run phase. Null hides the header badge. */
  phase?: string | null;
  /** Shared sample bar above the three columns. */
  sampleBar?: ReactNode;
  upstream: ReactNode;
  result: ReactNode;
  onClose: () => void;
  onChange: (nodeId: string, data: FlowNodeData) => void;
  onRun: (nodeId: string) => void;
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
  canRun,
  revealKey = null,
  problems = [],
  graph = EMPTY_GRAPH,
  scope,
  templatePreview = null,
  phase = null,
  sampleBar = null,
  upstream,
  result,
  onClose,
  onChange,
  onRun,
}: Props) {
  const t = useTranslate();
  const { data: heldPermissions } = usePermissions<string[]>({});
  const permission = spec?.permission ?? null;
  const configLocked = !canAuthorNodeType(permission, heldPermissions);
  const configEditable = editable && !configLocked;
  const typeLabel = spec ? nodeTypeLabel(t, spec) : data.nodeType;
  const summary = spec ? nodeTypeSummary(t, spec) : "";
  const fields = (schema ? fieldsFromSchema(schema) : []).filter((field) => {
    if (
      data.nodeType === "trigger.scheduled" &&
      ["cron", "interval_seconds", "start_at"].includes(field.key)
    ) {
      return false;
    }
    return fieldVisible(field, data.config);
  });
  const entityId = typeof data.config.entity_id === "string" ? data.config.entity_id : "";
  const head = useEntityHeadAttributes(entityId);
  const attached = new Set<string>(fields.map((field) => field.key));
  if (data.nodeType === "trigger.scheduled") {
    attached.add("cron");
    attached.add("interval_seconds");
    attached.add("start_at");
  }
  const nameProblems = problems.filter((problem) => problem.code === "CHANNEL_NODE_NAME_DUP");
  const refProblems = problems.filter((problem) => problem.code === "CHANNEL_NODE_REF_INVALID");
  const headerProblems = problems.filter((problem) => {
    if (nameProblems.includes(problem) || refProblems.includes(problem)) return false;
    const headKey = problem.path[0];
    return typeof headKey !== "string" || !attached.has(headKey);
  });
  const notesFor = (list: readonly GraphProblem[]) =>
    toNotes(
      list.map((problem) => ({
        text: formatGraphProblem(t, problem, graph, { nodeName: false }),
        severity: problem.severity === "warning" ? ("warning" as const) : ("error" as const),
      })),
    );
  const revealIn = (list: readonly GraphProblem[]) =>
    list.some((problem) => problemIdentity(problem) === revealKey) ? revealKey : null;
  const headerNotes = notesFor(headerProblems);
  const nodeName = (id: string) =>
    graph.nodes.find((node) => node.id === id)?.name.trim() || id;

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

  const allowsErrorOutput = spec?.outputs.some((port) => port.port === "error") ?? false;
  const onErrorValues = ["stop", "continue"];
  if (allowsErrorOutput) onErrorValues.push("error_output");
  if (!onErrorValues.includes(data.onError)) onErrorValues.push(data.onError);
  const onErrorOptions = onErrorValues.map((value) => ({
    value,
    label: t(`channels.node.onError.${value}`),
  }));

  const runAction =
    canRun === null ? undefined : (
      <Button size="compact-xs" variant="light" disabled={!canRun} onClick={() => onRun(nodeId)}>
        {t("channels.node.run")}
      </Button>
    );

  return (
    <FieldDisclosureContext.Provider value="quiet">
      <div className="channel-node-config__header">
        <Stack gap="xs">
          <Group justify="space-between" align="center" wrap="nowrap" gap="xs">
            <Group gap="xs" align="baseline" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={600} style={{ flex: "none" }}>
                {typeLabel}
              </Text>
              {summary ? (
                <Text size="xs" c="dimmed">
                  {summary}
                </Text>
              ) : null}
              {phase ? (
                <span className="channel-node-phase">
                  <StatusBadge
                    size="xs"
                    tone={presentNodeStatus(phase).tone}
                    labelKey={
                      phase === "waiting"
                        ? "channels.canvas.phase.waiting"
                        : presentNodeStatus(phase).labelKey
                    }
                  />
                </span>
              ) : null}
            </Group>
            <Group gap={4} wrap="nowrap">
              {headerNotes.length > 0 ? (
                <FieldMarks
                  label={data.name}
                  notes={headerNotes}
                  openSignal={revealIn(headerProblems)}
                />
              ) : null}
              {runAction}
              <CloseButton size="sm" aria-label={t("channels.node.close")} onClick={onClose} />
            </Group>
          </Group>
          <div className="channel-node-header-fields">
            <TextField
              editable={editable}
              label={t("channels.node.name")}
              notes={notesFor(nameProblems)}
              openSignal={revealIn(nameProblems)}
              value={data.name}
              onChange={(event) => update({ name: event.currentTarget.value })}
            />
            <TextField
              editable={editable}
              label={t("channels.node.ref")}
              notes={notesFor(refProblems)}
              openSignal={revealIn(refProblems)}
              value={data.ref}
              onChange={(event) => update({ ref: event.currentTarget.value })}
            />
          </div>
        </Stack>
      </div>
      {sampleBar}
      <div className="channel-node-detail">
        {upstream}
        <NodeRegion title={t("channels.node.config")}>
        <Stack gap="sm">
          {configLocked && permission ? (
            <Text size="xs" c="dimmed">
              {t("channels.node.permissionReadOnly", { permission })}
            </Text>
          ) : null}
          {data.nodeType === "trigger.scheduled" ? (
            <ScheduledCadenceFields
              config={data.config}
              editable={configEditable}
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
              nodeType={data.nodeType}
              value={data.config[field.key]}
              entityId={entityId}
              editable={configEditable}
              head={head}
              config={data.config}
              scope={data.config}
              templateScope={scope}
              runPreview={
                templatePreview
                  ? bindTemplatePreview(templatePreview, nodeId, [field.key], nodeName)
                  : null
              }
              messages={fieldMessages(t, problems, field.key, graph)}
              openSignal={signalFor(problems, field.key, revealKey)}
              onChange={(value) => setConfig(field.key, value)}
            />
          ))}
          <SelectField
            editable={editable}
            label={t("channels.node.onError")}
            data={onErrorOptions}
            value={data.onError}
            onChange={(next) => {
              if (next === "stop" || next === "continue" || next === "error_output") {
                update({ onError: next });
              }
            }}
            allowDeselect={false}
          />
          <NumberField
            editable={editable}
            label={t("channels.node.retryMax")}
            description={t("channels.node.retryMaxHint")}
            min={1}
            max={10}
            allowDecimal={false}
            value={data.retry?.max_tries ?? ""}
            onChange={(value) => {
              if (value === "" || value == null) {
                update({ retry: null });
                return;
              }
              const maxTries = Math.floor(Number(value));
              if (!Number.isFinite(maxTries)) return;
              update({
                retry: {
                  max_tries: Math.min(10, Math.max(1, maxTries)),
                  wait_sec: data.retry?.wait_sec ?? 0,
                },
              });
            }}
          />
          {data.retry ? (
            <NumberField
              editable={editable}
              label={t("channels.node.retryWait")}
              description={t("channels.node.retryWaitHint")}
              min={0}
              max={3600}
              allowDecimal={false}
              value={data.retry.wait_sec}
              onChange={(value) => {
                const wait = value === "" || value == null ? 0 : Math.floor(Number(value));
                if (!Number.isFinite(wait) || data.retry == null) return;
                update({
                  retry: {
                    max_tries: data.retry.max_tries,
                    wait_sec: Math.min(3600, Math.max(0, wait)),
                  },
                });
              }}
            />
          ) : null}
        </Stack>
        </NodeRegion>
        {result}
      </div>
    </FieldDisclosureContext.Provider>
  );
}

function ConfigField({
  field,
  nodeType,
  value,
  entityId,
  editable,
  labeled = true,
  exclude = [],
  head,
  config,
  scope,
  templateScope,
  runPreview = null,
  messages = [],
  openSignal = null,
  onChange,
}: {
  field: FieldSpec;
  nodeType: string;
  value: unknown;
  entityId: string;
  editable: boolean;
  labeled?: boolean;
  exclude?: readonly string[];
  head: HeadState;
  config: Record<string, unknown>;
  scope: Record<string, unknown>;
  templateScope: SelfScope;
  runPreview?: TemplatePreviewSource | null;
  messages?: readonly FieldMessage[];
  openSignal?: string | null;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const caption = fieldCaption(t, nodeType, field.key);
  const labelProps = labeled ? { label: caption } : { "aria-label": caption };
  const notes = toNotes(messages);
  const bare = !labeled;
  if (field.kind === "sql_source") {
    return (
      <SqlSourceField
        label={caption}
        description={fieldDescription(t, nodeType, field.key, field.description)}
        value={value}
        editable={editable}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "source") {
    return (
      <RegisteredSourceField
        label={caption}
        description={fieldDescription(t, nodeType, field.key, field.description)}
        value={value}
        editable={editable}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "webhook") {
    return (
      <WebhookField
        label={caption}
        description={fieldDescription(t, nodeType, field.key, field.description)}
        value={typeof value === "string" ? value : ""}
        editable={editable}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "email_account") {
    return (
      <EmailAccountField
        label={caption}
        description={fieldDescription(t, nodeType, field.key, field.description)}
        value={typeof value === "string" ? value : ""}
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
        nodeType={nodeType}
        value={value}
        entityId={entityId}
        editable={editable}
        head={head}
        config={config}
        templateScope={templateScope}
        notes={notes}
        openSignal={openSignal}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "stringList") {
    return (
      <StringListEditor
        field={field}
        nodeType={nodeType}
        value={value}
        editable={editable}
        notes={notes}
        openSignal={openSignal}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "templateList") {
    return (
      <TemplateListEditor
        field={field}
        nodeType={nodeType}
        value={value}
        editable={editable}
        templateScope={templateScope}
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
        description={fieldDescription(t, nodeType, field.key, field.description)}
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
  if (field.kind === "json") {
    return (
      <JsonObjectField
        label={labeled ? caption : undefined}
        aria-label={labeled ? undefined : caption}
        value={value}
        editable={editable}
        notes={notes}
        openSignal={openSignal}
        bare={bare}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "template") {
    const valueSchema = "from" in field.valueSchema ? attributeSchema(scope, head) : field.valueSchema;
    return (
      <TemplateField
        label={labeled ? caption : undefined}
        ariaLabel={labeled ? undefined : caption}
        description={fieldDescription(t, nodeType, field.key, field.description)}
        valueSchema={valueSchema}
        value={typeof value === "string" ? value : ""}
        editable={editable}
        scope={templateScope}
        messages={messages}
        openSignal={openSignal}
        runPreview={runPreview}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "python") {
    return (
      <PythonCodeField
        label={caption}
        description={fieldDescription(t, nodeType, field.key, field.description)}
        value={typeof value === "string" ? value : ""}
        editable={editable}
        notes={notes}
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
      onChange={(event) => {
        const text = event.currentTarget.value;
        onChange(field.nullable && text === "" ? null : text);
      }}
    />
  );
}

function ObjectListEditor({
  field,
  nodeType,
  value,
  entityId,
  editable,
  head,
  config,
  templateScope,
  notes,
  openSignal = null,
  onChange,
}: {
  field: Extract<FieldSpec, { kind: "objectList" }>;
  nodeType: string;
  value: unknown;
  entityId: string;
  editable: boolean;
  head: HeadState;
  config: Record<string, unknown>;
  templateScope: SelfScope;
  notes: readonly FieldNote[];
  openSignal?: string | null;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const label = fieldCaption(t, nodeType, field.key);
  const rows = Array.isArray(value) ? value.filter(isRecord) : [];
  const columns = field.fields.filter((child) => rows.some((row) => fieldVisible(child, row)));
  const taken = attributeNames(rows);
  const addBlocked =
    field.key === "mapping" &&
    head.ready &&
    !head.attributes.some((attribute) => !taken.has(attribute.name));
  const columnClass =
    columns.length >= 3
      ? "channel-config-grid--3"
      : columns.length === 1
        ? "channel-config-grid--1"
        : "channel-config-grid--2";

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
      {columns.length > 0 ? (
        <div
          className={[
            "channel-config-grid",
            columnClass,
            editable ? "channel-config-grid--actions" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {columns.map((child) => (
            <Text key={child.key} size="xs" fw={500} c="dimmed">
              {fieldCaption(t, nodeType, child.key)}
            </Text>
          ))}
          {editable ? <span /> : null}
          {rows.map((row, index) => (
            <ListRow
              key={`${field.key}-${index}`}
              field={field}
              columns={columns}
              nodeType={nodeType}
              row={row}
              index={index}
              rows={rows}
              entityId={entityId}
              editable={editable}
              head={head}
              config={config}
              templateScope={templateScope}
              onChange={onChange}
            />
          ))}
        </div>
      ) : null}
    </Stack>
  );
}

function StringListEditor({
  field,
  nodeType,
  value,
  editable,
  notes,
  openSignal = null,
  onChange,
}: {
  field: Extract<FieldSpec, { kind: "stringList" }>;
  nodeType: string;
  value: unknown;
  editable: boolean;
  notes: readonly FieldNote[];
  openSignal?: string | null;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const label = fieldCaption(t, nodeType, field.key);
  const items = Array.isArray(value) ? value.map((item) => (typeof item === "string" ? item : "")) : [];
  return (
    <Stack gap="xs">
      <ListHeading
        label={label}
        description={field.description}
        notes={notes}
        openSignal={openSignal}
        editable={editable}
        onAdd={() => onChange([...items, ""])}
      />
      {items.map((item, index) => (
        <Group key={`${field.key}-${index}`} gap="xs" wrap="nowrap" align="center">
          <TextField
            editable={editable}
            aria-label={t("channels.config.listItem", { label, n: index + 1 })}
            value={item}
            bare
            style={{ flex: 1 }}
            onChange={(event) => {
              const next = [...items];
              next[index] = event.currentTarget.value;
              onChange(next);
            }}
          />
          {editable ? <RemoveItem onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))} /> : null}
        </Group>
      ))}
    </Stack>
  );
}

function TemplateListEditor({
  field,
  nodeType,
  value,
  editable,
  templateScope,
  notes,
  openSignal = null,
  onChange,
}: {
  field: Extract<FieldSpec, { kind: "templateList" }>;
  nodeType: string;
  value: unknown;
  editable: boolean;
  templateScope: SelfScope;
  notes: readonly FieldNote[];
  openSignal?: string | null;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const label = fieldCaption(t, nodeType, field.key);
  const items = Array.isArray(value) ? value.map((item) => (typeof item === "string" ? item : "")) : [];
  return (
    <Stack gap="xs">
      <ListHeading
        label={label}
        description={field.description}
        notes={notes}
        openSignal={openSignal}
        editable={editable}
        onAdd={() => onChange([...items, ""])}
      />
      {items.map((item, index) => (
        <Group key={`${field.key}-${index}`} gap="xs" wrap="nowrap" align="flex-start">
          <div style={{ flex: 1, minWidth: 0 }}>
            <TemplateField
              ariaLabel={t("channels.config.listItem", { label, n: index + 1 })}
              description={field.itemDescription}
              valueSchema={field.valueSchema}
              value={item}
              editable={editable}
              scope={templateScope}
              onChange={(next) => {
                const copy = [...items];
                copy[index] = next;
                onChange(copy);
              }}
            />
          </div>
          {editable ? <RemoveItem onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))} /> : null}
        </Group>
      ))}
    </Stack>
  );
}

function ListHeading({
  label,
  description,
  notes,
  openSignal,
  editable,
  onAdd,
}: {
  label: string;
  description: string;
  notes: readonly FieldNote[];
  openSignal?: string | null;
  editable: boolean;
  onAdd: () => void;
}) {
  const t = useTranslate();
  return (
    <Group justify="space-between">
      <Group gap={4} wrap="nowrap">
        <Text size="sm" fw={500}>
          {label}
        </Text>
        <FieldMarks label={label} description={description} notes={notes} openSignal={openSignal} />
      </Group>
      {editable ? (
        <Button type="button" size="xs" variant="light" onClick={onAdd}>
          {t("channels.config.addItem")}
        </Button>
      ) : null}
    </Group>
  );
}

function RemoveItem({ onClick }: { onClick: () => void }) {
  const t = useTranslate();
  return (
    <ActionIcon
      variant="subtle"
      color="red"
      size="sm"
      aria-label={t("channels.config.removeItem")}
      onClick={onClick}
    >
      ×
    </ActionIcon>
  );
}

function ListRow({
  field,
  columns,
  nodeType,
  row,
  index,
  rows,
  entityId,
  editable,
  head,
  config,
  templateScope,
  onChange,
}: {
  field: Extract<FieldSpec, { kind: "objectList" }>;
  columns: FieldSpec[];
  nodeType: string;
  row: Record<string, unknown>;
  index: number;
  rows: Record<string, unknown>[];
  entityId: string;
  editable: boolean;
  head: HeadState;
  config: Record<string, unknown>;
  templateScope: SelfScope;
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
      {columns.map((child) => (
        <div key={child.key} className="channel-config-grid__cell">
          {fieldVisible(child, row) ? (
            <ConfigField
              field={child}
              nodeType={nodeType}
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
              templateScope={templateScope}
              onChange={(next) => replace(child.key, next)}
            />
          ) : null}
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

function fieldDescription(
  t: (key: string, options?: Record<string, unknown>) => string,
  nodeType: string,
  key: string,
  fallback: string,
): string {
  return lookupCaption(t, `channels.config.fields.${nodeType}.${key}.description`) ?? fallback;
}

function fieldCaption(
  t: (key: string, options?: Record<string, unknown>) => string,
  nodeType: string,
  key: string,
): string {
  const specific = lookupCaption(t, `channels.config.fields.${nodeType}.${key}`);
  if (specific) return specific;
  const general = lookupCaption(t, `channels.config.fields.${key}`);
  return general ?? key;
}

function lookupCaption(
  t: (key: string, options?: Record<string, unknown>) => string,
  key: string,
): string | null {
  const text = t(key, { defaultValue: "" });
  if (!text || text === key) return null;
  return text;
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

const RESERVED_PAYLOAD_KEYS = new Set(["triggered_by", "triggered_at"]);

function parsedObject(value: unknown): Record<string, unknown> | null {
  if (isRecord(value)) return value;
  if (typeof value !== "string" || value.trim() === "") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function JsonObjectField({
  label,
  "aria-label": ariaLabel,
  value,
  editable,
  notes,
  openSignal,
  bare,
  onChange,
}: {
  label?: string;
  "aria-label"?: string;
  value: unknown;
  editable: boolean;
  notes: readonly FieldNote[];
  openSignal?: string | null;
  bare?: boolean;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const hint = t("channels.config.json.hint");
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  useEffect(() => {
    if (typeof value !== "string") return;
    const trimmed = value.trim();
    if (trimmed === "") {
      onChangeRef.current({});
      return;
    }
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (isRecord(parsed)) onChangeRef.current(parsed);
    } catch {
      return;
    }
  }, [value]);

  const parsed = parsedObject(value);
  const reserved = parsed != null && Object.keys(parsed).some((key) => RESERVED_PAYLOAD_KEYS.has(key));
  const kept = notes.filter((note) => {
    const text = typeof note.text === "string" ? note.text : "";
    if (!isRecord(value) && text.includes("is not of type")) return false;
    if (reserved && text.includes("reserved key")) return false;
    return true;
  });
  const reservedNotes: FieldNote[] = reserved
    ? [{ text: t("channels.config.json.reserved"), tone: "error" }]
    : [];
  return (
    <JsonField
      editable={editable}
      label={label}
      aria-label={ariaLabel}
      hint={hint}
      invalidMessage={hint}
      value={value === undefined ? {} : value}
      accept={isRecord}
      onEmpty={() => onChange({})}
      notes={[...reservedNotes, ...kept]}
      openSignal={openSignal}
      bare={bare}
      onChange={onChange}
    />
  );
}

function attributeSchema(scope: Record<string, unknown>, head: HeadState) {
  const name = typeof scope.attribute === "string" ? scope.attribute : "";
  const attribute = head.attributes.find((item) => item.name === name);
  return attribute ? attributeValueSchema(attribute.type) : null;
}
