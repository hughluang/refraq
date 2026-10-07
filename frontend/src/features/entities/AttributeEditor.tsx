"use client";

import { Button, Drawer, Group, Stack, Table, Text } from "@mantine/core";
import type { UseFormReturnType } from "@mantine/form";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { FieldDisplay } from "@/components/form/FieldDisplay";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import { DictionarySelect } from "@/features/dictionaries/DictionarySelect";
import {
  attributeConfigSummary,
  attributeDraftIssues,
  type AttributeIssue,
  type AttributeIssueField,
} from "@/features/entities/attributeDraftValidation";
import {
  ATTRIBUTE_TYPE_CATALOG,
  ATTRIBUTE_TYPES,
} from "@/features/entities/attributeTypes.generated";
import { EMPTY_ATTRIBUTE } from "@/features/entities/constants";
import { physicalColumnType } from "@/features/entities/physicalType";
import { referenceSummaryLabel } from "@/features/entities/entityPresentation";
import { TargetEntityField } from "@/features/entities/TargetEntityField";
import type {
  AttributeDraft,
  AttributeType,
  EntityRecordFormValues,
} from "@/features/entities/types";

export type AttributeReveal = {
  index: number;
  nonce: number;
};

type DrawerState = {
  kind: "create" | "edit";
  index: number | null;
  draft: AttributeDraft;
  issues: AttributeIssue[];
};

type Props = {
  form: UseFormReturnType<EntityRecordFormValues>;
  editable: boolean;
  selfEntityId: string | null;
  onEditingChange?: (open: boolean) => void;
  reveal?: AttributeReveal | null;
};

function integerValue(value: string): number | undefined {
  if (value === "") return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function namesFor(
  attributes: AttributeDraft[],
  draft: AttributeDraft,
  index: number | null,
): string[] {
  if (index == null) {
    return [...attributes.map((item) => item.name), draft.name];
  }
  return attributes.map((item, itemIndex) =>
    itemIndex === index ? draft.name : item.name,
  );
}

export function AttributeEditor({
  form,
  editable,
  selfEntityId,
  onEditingChange,
  reveal,
}: Props) {
  const t = useTranslate();
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const attributes = form.values.attributes;
  const locked = drawer != null;
  const typeOptions = ATTRIBUTE_TYPES.map((value) => ({
    value,
    label: t(`entities.attributeType.${value}`),
  }));

  const changeDrawer = (next: DrawerState | null) => {
    setDrawer(next);
    onEditingChange?.(next != null);
  };

  useEffect(() => {
    if (!editable) changeDrawer(null);
  }, [editable]);

  useEffect(() => {
    if (!editable || reveal == null) return;
    const source = form.values.attributes[reveal.index];
    if (!source) return;
    const draft = { ...source };
    changeDrawer({
      kind: "edit",
      index: reveal.index,
      draft,
      issues: attributeDraftIssues(
        draft,
        form.values.attributes.map((item) => item.name),
        form.values.attributes.filter((_, index) => index !== reveal.index),
      ),
    });
  }, [editable, reveal]);

  const openEdit = (index: number) => {
    if (!editable || locked) return;
    const source = attributes[index];
    if (!source) return;
    changeDrawer({
      kind: "edit",
      index,
      draft: { ...source },
      issues: [],
    });
  };

  const openCreate = () => {
    if (!editable || locked) return;
    changeDrawer({
      kind: "create",
      index: null,
      draft: { ...EMPTY_ATTRIBUTE },
      issues: [],
    });
  };

  const closeDrawer = () => changeDrawer(null);

  const confirmDrawer = () => {
    if (!drawer) return;
    const siblings = attributes.filter((_, index) => index !== drawer.index);
    const issues = attributeDraftIssues(
      drawer.draft,
      namesFor(attributes, drawer.draft, drawer.index),
      siblings,
    );
    if (issues.length > 0) {
      changeDrawer({ ...drawer, issues });
      return;
    }
    if (drawer.kind === "create") {
      form.insertListItem("attributes", drawer.draft);
    } else if (drawer.index != null) {
      form.replaceListItem("attributes", drawer.index, drawer.draft);
    }
    changeDrawer(null);
  };

  const updateDraft = (patch: Partial<AttributeDraft>) => {
    setDrawer((current) =>
      current
        ? { ...current, draft: { ...current.draft, ...patch } }
        : current,
    );
  };

  const issueMessage = (field: AttributeIssueField): string | undefined => {
    const issue = drawer?.issues.find((item) => item.field === field);
    if (!issue) return undefined;
    return issue.values ? t(issue.key, issue.values) : t(issue.key);
  };

  const configText = (attr: AttributeDraft): string | null => {
    if (attr.type === "reference") {
      return referenceSummaryLabel({
        targetEntityId: attr.target_entity_id,
        selfEntityId,
        selfName: form.values.name,
        selfTableName: form.values.table_name,
        cachedName: attr.target_name,
        cachedTableName: attr.target_table_name,
        emptyNameLabel: t("entities.attributes.selfEntity"),
      });
    }
    const fact = attributeConfigSummary(attr);
    if (!fact) return null;
    if (fact.kind === "max_length") {
      return t("entities.attributes.config.maxLength", {
        label: t("entities.fields.maxLength"),
        value: fact.value,
      });
    }
    if (fact.kind === "decimal") {
      return t("entities.attributes.config.decimal", {
        precisionLabel: t("entities.fields.precision"),
        precision: fact.precision,
        scaleLabel: t("entities.fields.scale"),
        scale: fact.scale,
      });
    }
    return fact.label;
  };

  const draft = drawer?.draft;
  const liveTitle =
    draft == null
      ? null
      : draft.name.trim()
        ? draft.name.trim()
        : drawer?.kind === "create"
          ? t("entities.attributes.drawer.create")
          : t("entities.attributes.drawer.untitled");
  const titleRef = useRef(liveTitle ?? "");
  if (liveTitle) titleRef.current = liveTitle;

  return (
    <Stack gap="sm">
      <Table.ScrollContainer minWidth={720}>
        <Table highlightOnHover={editable && !locked} horizontalSpacing="sm" verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("entities.fields.attributeName")}</Table.Th>
              <Table.Th>{t("entities.fields.attributeType")}</Table.Th>
              <Table.Th>{t("entities.fields.attributeConfig")}</Table.Th>
              <Table.Th>{t("entities.fields.required")}</Table.Th>
              <Table.Th>{t("entities.fields.unique")}</Table.Th>
              <Table.Th>{t("entities.fields.indexed")}</Table.Th>
              <Table.Th>{t("entities.fields.businessKey")}</Table.Th>
              <Table.Th>{t("entities.fields.attributeDescription")}</Table.Th>
              {editable ? <Table.Th>{t("actions.delete")}</Table.Th> : null}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {attributes.map((attr, index) => {
              const config = configText(attr);
              return (
                <Table.Tr
                  key={index}
                  onClick={() => openEdit(index)}
                  style={
                    editable && !locked ? { cursor: "pointer" } : undefined
                  }
                >
                  <Table.Td>
                    <Text size="sm">{attr.name}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap={2}>
                      <Text size="sm">
                        {t(`entities.attributeType.${attr.type}`)}
                      </Text>
                      <Text size="xs" c="dimmed" ff="monospace">
                        {physicalColumnType(attr)}
                      </Text>
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    {config ? <Text size="sm">{config}</Text> : null}
                    {attr.behind ? (
                      <Text size="xs" c="orange">
                        {t("entities.attributes.behind")}
                      </Text>
                    ) : null}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {attr.required ? t("form.value.yes") : t("form.value.no")}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {attr.unique ? t("form.value.yes") : t("form.value.no")}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {attr.indexed ? t("form.value.yes") : t("form.value.no")}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {attr.business_key ? t("form.value.yes") : t("form.value.no")}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{attr.description}</Text>
                  </Table.Td>
                  {editable ? (
                    <Table.Td>
                      <Button
                        type="button"
                        size="xs"
                        variant="subtle"
                        color="red"
                        disabled={locked && drawer?.index !== index}
                        onClick={(event) => {
                          event.stopPropagation();
                          form.removeListItem("attributes", index);
                          if (drawer?.kind === "edit" && drawer.index === index) {
                            changeDrawer(null);
                          }
                        }}
                      >
                        {t("actions.delete")}
                      </Button>
                    </Table.Td>
                  ) : null}
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {editable ? (
        <Button
          type="button"
          size="xs"
          variant="light"
          disabled={locked}
          onClick={openCreate}
        >
          {t("entities.attributes.add")}
        </Button>
      ) : null}
      <Drawer
        opened={drawer != null}
        onClose={closeDrawer}
        position="right"
        size="md"
        title={titleRef.current}
      >
        {draft ? (
          <Stack gap="sm">
            <TextField
              editable
              label={t("entities.attributes.drawer.name")}
              value={draft.name}
              onChange={(event) => updateDraft({ name: event.currentTarget.value })}
              error={issueMessage("name")}
            />
            <SelectField
              editable
              label={t("entities.attributes.drawer.type")}
              data={typeOptions}
              allowDeselect={false}
              value={draft.type}
              onChange={(value) =>
                updateDraft({ type: (value ?? draft.type) as AttributeType })
              }
            />
            {draft.type === "user" ? (
              <Text size="sm" c="dimmed">
                {t("entities.attributeType.userHint")}
              </Text>
            ) : null}
            <FieldDisplay
              label={t("entities.fields.databaseType")}
              value={
                <Text ff="monospace" size="sm">
                  {physicalColumnType(draft)}
                </Text>
              }
            />
            {draft.type === "string" ? (
              <NumberField
                editable
                required
                label={t("entities.fields.maxLength")}
                min={ATTRIBUTE_TYPE_CATALOG.string.config.max_length.minimum}
                max={ATTRIBUTE_TYPE_CATALOG.string.config.max_length.maximum}
                allowDecimal={false}
                value={integerValue(draft.max_length)}
                onChange={(value) =>
                  updateDraft({
                    max_length:
                      value === "" || value == null ? "" : String(value),
                  })
                }
                error={issueMessage("max_length")}
              />
            ) : null}
            {draft.type === "decimal" ? (
              <Group grow>
                <NumberField
                  editable
                  required
                  label={t("entities.fields.precision")}
                  min={ATTRIBUTE_TYPE_CATALOG.decimal.config.precision.minimum}
                  max={ATTRIBUTE_TYPE_CATALOG.decimal.config.precision.maximum}
                  allowDecimal={false}
                  value={integerValue(draft.precision)}
                  onChange={(value) =>
                    updateDraft({
                      precision:
                        value === "" || value == null ? "" : String(value),
                    })
                  }
                  error={issueMessage("precision")}
                />
                <NumberField
                  editable
                  required
                  label={t("entities.fields.scale")}
                  min={ATTRIBUTE_TYPE_CATALOG.decimal.config.scale.minimum}
                  max={ATTRIBUTE_TYPE_CATALOG.decimal.config.scale.maximum}
                  allowDecimal={false}
                  value={integerValue(draft.scale)}
                  onChange={(value) =>
                    updateDraft({
                      scale: value === "" || value == null ? "" : String(value),
                    })
                  }
                  error={issueMessage("scale")}
                />
              </Group>
            ) : null}
            {draft.type === "reference" ? (
              <TargetEntityField
                required
                label={t("entities.fields.targetTableName")}
                error={issueMessage("target_entity_id")}
                value={draft.target_entity_id}
                selfEntityId={selfEntityId}
                selfName={form.values.name}
                selfTableName={form.values.table_name}
                cachedName={draft.target_name}
                cachedTableName={draft.target_table_name}
                onChange={(next) => updateDraft(next)}
              />
            ) : null}
            {draft.type === "dictionary" ? (
              <DictionarySelect
                editable
                value={draft.dictionary_id}
                name={draft.dictionary_name}
                displayName={draft.dictionary_display_name}
                deprecated={draft.dictionary_deprecated}
                behind={draft.behind}
                error={issueMessage("dictionary_id")}
                onChange={(next) => updateDraft(next)}
              />
            ) : null}
            <SwitchField
              editable
              label={t("entities.fields.required")}
              checked={draft.required}
              onChange={(event) =>
                updateDraft({ required: event.currentTarget.checked })
              }
            />
            <SwitchField
              editable
              label={t("entities.fields.unique")}
              checked={draft.unique}
              onChange={(event) =>
                updateDraft({ unique: event.currentTarget.checked })
              }
            />
            <SwitchField
              editable
              label={t("entities.fields.indexed")}
              checked={draft.indexed}
              onChange={(event) =>
                updateDraft({ indexed: event.currentTarget.checked })
              }
            />
            <SwitchField
              editable
              label={t("entities.fields.businessKey")}
              description={t("entities.fields.businessKeyHint")}
              checked={draft.business_key}
              onChange={(event) =>
                updateDraft({ business_key: event.currentTarget.checked })
              }
              error={issueMessage("business_key")}
            />
            <TextField
              editable
              label={t("entities.attributes.drawer.description")}
              value={draft.description}
              onChange={(event) =>
                updateDraft({ description: event.currentTarget.value })
              }
            />
            <Group justify="flex-end">
              <Button type="button" variant="default" onClick={closeDrawer}>
                {t("entities.attributes.drawer.cancel")}
              </Button>
              <Button type="button" onClick={confirmDrawer}>
                {t("entities.attributes.drawer.confirm")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Drawer>
    </Stack>
  );
}
