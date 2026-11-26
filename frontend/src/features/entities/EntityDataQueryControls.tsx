"use client";

import {
  ActionIcon,
  Button,
  CloseButton,
  Group,
  MultiSelect,
  Select,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { FilterIcon, SearchIcon } from "@/components/icons";
import { useEffect, useId, useState, type KeyboardEvent, type ReactNode } from "react";

import type { DataAttribute, DataSchema } from "./accessTypes";
import { attributeDisplayLabel, attributeTitle } from "./entityPresentation";
import {
  compileDataQuery,
  conditionOps,
  EMPTY_DATA_QUERY,
  inputTypeOf,
  lookupFields,
  lookupOp,
  queryFields,
  type EntityDataQuery,
  type QueryCondition,
} from "./entityDataQuery";
import { useEntryZone } from "@/hooks/useFormatInstant";
import { instantToWall, wallToInstant } from "@/lib/wall-time";
import classes from "./EntityDataQueryControls.module.css";

const key = "entities.data.query.";
const opKey = (op: string, field?: DataAttribute) => {
  if (op === "between") return key + "between";
  const isTime = field && ["date", "time", "timestamp"].includes(field.type);
  const suffix = isTime && ["lt", "lte", "gt", "gte"].includes(op) ? ".time" : "";
  return "entities.access.rule.op." + op + suffix;
};

function initialCondition(field: DataAttribute, op = conditionOps(field)[0]): QueryCondition {
  const values = op === "is_null" ? [] : op === "between" ? ["", ""] : [""];
  return { field: field.name, op, values };
}

function onSubmitKey(event: KeyboardEvent<HTMLInputElement>, submit: () => void) {
  if (event.key === "Enter" && !event.nativeEvent.isComposing) {
    event.preventDefault();
    event.stopPropagation();
    submit();
  }
}

function InstantInput({ label, value, onChange, submit, compact, disabled }: ScalarProps) {
  const zone = useEntryZone();
  return (
    <TextInput
      label={compact ? undefined : label + " (" + zone + ")"}
      aria-label={label + " (" + zone + ")"}
      title={label + " (" + zone + ")"}
      disabled={disabled}
      type="datetime-local"
      step="1"
      value={instantToWall(value, zone, "T") ?? ""}
      onChange={(e) => onChange(wallToInstant(e.currentTarget.value, zone) ?? "")}
      onKeyDown={(e) => onSubmitKey(e, submit)}
    />
  );
}

type ScalarProps = {
  label: string;
  value: string;
  onChange: (v: string) => void;
  submit: () => void;
  compact?: boolean;
  disabled?: boolean;
};

function ValueInput({ field, ...props }: ScalarProps & { field: DataAttribute }) {
  const t = useTranslate();
  const { label, value, onChange, submit, compact, disabled } = props;
  const kind = inputTypeOf(field);
  if (kind === "timestamp") return <InstantInput {...props} />;
  if (kind === "dictionary" || kind === "boolean") {
    const options =
      kind === "boolean"
        ? [
            { value: "true", label: t("form.value.yes") },
            { value: "false", label: t("form.value.no") },
          ]
        : (field.codes ?? []).map((c) => ({
            value: c.code,
            label: c.label ? c.label + " (" + c.code + ")" : c.code,
          }));
    return (
      <Select
        label={compact ? undefined : label}
        aria-label={label}
        disabled={disabled}
        placeholder={label}
        value={value || null}
        data={options}
        searchable={kind === "dictionary"}
        clearable={compact && Boolean(value)}
        allowDeselect={false}
        onChange={(v) => onChange(v ?? "")}
      />
    );
  }
  return (
    <TextInput
      type={kind === "date" || kind === "time" ? kind : "text"}
      step={kind === "time" ? "any" : undefined}
      label={compact ? undefined : label}
      aria-label={label}
      value={value}
      disabled={disabled}
      inputMode={
        kind === "integer"
          ? "numeric"
          : ["number", "decimal"].includes(kind)
            ? "decimal"
            : undefined
      }
      placeholder={compact ? label : kind === "json" ? "JSON" : undefined}
      onChange={(e) => onChange(e.currentTarget.value)}
      onKeyDown={(e) => onSubmitKey(e, submit)}
    />
  );
}

type Props = {
  schema: DataSchema;
  query: EntityDataQuery;
  onChange: (next: EntityDataQuery) => void;
  disabled?: boolean;
  columnAction?: ReactNode;
  actions?: ReactNode;
};

export function EntityDataQueryControls({
  schema,
  query,
  onChange,
  disabled = false,
  columnAction,
  actions,
}: Props) {
  const t = useTranslate();
  const editorId = useId();
  const fields = queryFields(schema);
  const searchable = lookupFields(schema, fields);
  const preferred = searchable[0]?.name ?? "";
  const [quickField, setQuickField] = useState(query.lookup?.field ?? preferred);
  const [quickValue, setQuickValue] = useState(query.lookup?.value ?? "");
  const [editor, setEditor] = useState<{ index: number | null; draft: QueryCondition } | null>(
    null,
  );
  const [quickError, setQuickError] = useState("");
  const [filterError, setFilterError] = useState("");
  const [match, setMatch] = useState(query.match);
  useEffect(() => {
    setQuickField(query.lookup?.field ?? preferred);
    setQuickValue(query.lookup?.value ?? "");
    setQuickError("");
  }, [query.lookup?.field, query.lookup?.value, preferred]);
  useEffect(() => {
    setEditor(null);
    setFilterError("");
    setMatch(query.match);
  }, [query, schema]);

  function search() {
    const lookup = quickValue !== "" ? { field: quickField, value: quickValue } : null;
    const next = { ...query, lookup };
    const compiled = compileDataQuery(next, schema);
    if (!compiled.ok) {
      setQuickError(t(compiled.error));
      return;
    }
    setQuickError("");
    onChange(next);
  }

  function startEdit(draft: QueryCondition, index: number | null) {
    setEditor({ index, draft });
    setFilterError("");
    setMatch(query.match);
  }

  function updateDraft(next: QueryCondition) {
    if (editor) setEditor({ ...editor, draft: next });
    setFilterError("");
  }

  function apply() {
    if (!editor) return;
    const conditions = [...query.conditions];
    conditions[editor.index ?? conditions.length] = editor.draft;
    const next = { ...query, match, conditions };
    const compiled = compileDataQuery(next, schema);
    if (!compiled.ok) {
      setFilterError(t(compiled.error));
      return;
    }
    setEditor(null);
    onChange(next);
  }

  const draft = editor?.draft;
  const field = fields.find((item) => item.name === draft?.field);
  const quickAttribute = searchable.find((f) => f.name === quickField) ?? searchable[0];
  const activeLookup = fields.find((f) => f.name === query.lookup?.field);
  const quickLabel = t(
    key +
      (quickAttribute && lookupOp(schema, quickAttribute) === "contains" ? "contains" : "exact"),
    { field: quickAttribute ? attributeTitle(quickAttribute) : quickField },
  );
  const hasFilters = Boolean(query.lookup || query.conditions.length);
  const firstFilter = fields.find((f) => f.name === schema.business_key) ?? fields[0];

  return (
    <Stack gap="xs">
      <Group gap="xs" align="center" className={classes.toolbar}>
        {quickAttribute && (
          <div className={classes.search}>
            <Select
              aria-label={t(key + "searchField")}
              data={searchable.map((f) => ({ value: f.name, label: attributeDisplayLabel(f) }))}
              value={quickField}
              allowDeselect={false}
              searchable={searchable.length > 8}
              disabled={disabled}
              className={classes.searchField}
              onChange={(v) => {
                if (v && v !== quickField) {
                  setQuickField(v);
                  setQuickValue("");
                  setQuickError("");
                }
              }}
            />
            <div className={classes.searchValue}>
              <ValueInput
                field={quickAttribute}
                label={quickLabel}
                compact
                disabled={disabled}
                value={quickValue}
                onChange={(v) => {
                  setQuickValue(v);
                  setQuickError("");
                  if (v === "" && query.lookup) onChange({ ...query, lookup: null });
                }}
                submit={search}
              />
            </div>
            <ActionIcon
              type="button"
              className={classes.submitSearch}
              variant="default"
              size="lg"
              title={t("common.list.search")}
              aria-label={t("common.list.search")}
              onClick={search}
              disabled={disabled}
            >
              <SearchIcon size={16} />
            </ActionIcon>
          </div>
        )}
        {firstFilter && (
          <Button
            type="button"
            variant={editor ? "light" : "default"}
            leftSection={<FilterIcon size={16} />}
            disabled={disabled}
            aria-expanded={Boolean(editor)}
            aria-controls={editorId}
            onClick={() => {
              if (editor) setEditor(null);
              else startEdit(initialCondition(firstFilter), null);
            }}
          >
            {t(key + "filter")}
          </Button>
        )}
        {columnAction}
        {actions && (
          <Group className={classes.viewActions} gap="xs">
            {actions}
          </Group>
        )}
      </Group>
      {quickError && (
        <Text c="red" size="sm" role="alert">
          {quickError}
        </Text>
      )}
      {hasFilters && (
        <Group gap={6} className={classes.conditions}>
          {query.lookup && (
            <div className={classes.chip}>
              <span className={classes.chipLabel}>
                {activeLookup ? attributeTitle(activeLookup) : query.lookup.field}{" "}
                {t(opKey(activeLookup ? (lookupOp(schema, activeLookup) ?? "eq") : "eq"))}{" "}
                {query.lookup.value}
              </span>
              <CloseButton
                size="xs"
                type="button"
                aria-label={t("common.search.clear")}
                disabled={disabled}
                onClick={() => onChange({ ...query, lookup: null })}
              />
            </div>
          )}
          {query.conditions.length > 1 && (
            <Text size="xs" fw={600}>
              {t(key + (query.match === "all" ? "all" : "any"))}
            </Text>
          )}
          {query.conditions.map((condition, index) => {
            const condField = fields.find((f) => f.name === condition.field);
            const label = [
              condField ? attributeTitle(condField) : condition.field,
              t(
                opKey(
                  condition.op,
                  condField,
                ),
              ),
              condition.values.join(condition.op === "between" ? " – " : ", "),
            ]
              .join(" ")
              .trim();
            return (
              <div key={index} className={classes.chip}>
                <UnstyledButton
                  type="button"
                  className={classes.chipLabel}
                  title={label}
                  disabled={disabled}
                  onClick={() => startEdit(condition, index)}
                >
                  {label}
                </UnstyledButton>
                <CloseButton
                  size="xs"
                  type="button"
                  aria-label={t(key + "remove", { condition: label })}
                  disabled={disabled}
                  onClick={() =>
                    onChange({
                      ...query,
                      conditions: query.conditions.filter((_, i) => i !== index),
                    })
                  }
                />
              </div>
            );
          })}
          <Button
            size="compact-xs"
            variant="subtle"
            type="button"
            disabled={disabled}
            onClick={() => onChange(EMPTY_DATA_QUERY)}
          >
            {t("common.filters.clear")}
          </Button>
        </Group>
      )}
      {editor && draft && field && (
        <div id={editorId} className={classes.editor}>
          <Group gap="xs" align="end" className={classes.editorFields}>
            {(query.conditions.length > 1 ||
              (query.conditions.length === 1 && editor.index === null)) && (
              <Select
                label={t(key + "match")}
                data={[
                  { value: "all", label: t(key + "all") },
                  { value: "any", label: t(key + "any") },
                ]}
                value={match}
                allowDeselect={false}
                onChange={(v) => setMatch(v === "any" ? "any" : "all")}
              />
            )}
            <Select
              label={t(key + "field")}
              value={field.name}
              data={fields.map((f) => ({ value: f.name, label: attributeDisplayLabel(f) }))}
              searchable={fields.length > 8}
              allowDeselect={false}
              onChange={(v) => {
                const nextField = fields.find((f) => f.name === v);
                if (nextField) updateDraft(initialCondition(nextField));
              }}
            />
            <Select
              label={t(key + "comparison")}
              value={draft.op}
              allowDeselect={false}
              data={conditionOps(field).map((op) => ({ value: op, label: t(opKey(op, field)) }))}
              onChange={(op) => {
                if (op) updateDraft(initialCondition(field, op));
              }}
            />
            {draft.op === "in" && field.type === "dictionary" ? (
              <MultiSelect
                searchable
                label={t(key + "values")}
                value={draft.values.filter(Boolean)}
                data={(field.codes ?? []).map((c) => ({
                  value: c.code,
                  label: c.label ? c.label + " (" + c.code + ")" : c.code,
                }))}
                onChange={(values) => updateDraft({ ...draft, values })}
              />
            ) : (
              draft.values.map((value, i) => (
                <div className={classes.value} key={i}>
                  <ValueInput
                    field={field}
                    value={value}
                    label={
                      draft.op === "between"
                        ? t(key + (i === 0 ? "from" : "through"))
                        : t(key + "value")
                    }
                    onChange={(v) =>
                      updateDraft({
                        ...draft,
                        values: draft.values.map((old, j) => (i === j ? v : old)),
                      })
                    }
                    submit={apply}
                  />
                  {draft.op === "in" && draft.values.length > 1 && (
                    <CloseButton
                      type="button"
                      aria-label={t(key + "removeValue")}
                      onClick={() =>
                        updateDraft({ ...draft, values: draft.values.filter((_, j) => i !== j) })
                      }
                    />
                  )}
                </div>
              ))
            )}
          </Group>
          <Group gap="xs" mt="sm">
            {draft.op === "in" && field.type !== "dictionary" && (
              <Button
                type="button"
                variant="default"
                size="xs"
                onClick={() => updateDraft({ ...draft, values: [...draft.values, ""] })}
              >
                {t(key + "addValue")}
              </Button>
            )}
            <Button type="button" size="xs" onClick={apply} disabled={disabled}>
              {t(key + "apply")}
            </Button>
            <Button type="button" variant="subtle" size="xs" onClick={() => setEditor(null)}>
              {t("common.cancel")}
            </Button>
            {filterError && (
              <Text c="red" size="sm" role="alert">
                {filterError}
              </Text>
            )}
          </Group>
        </div>
      )}
    </Stack>
  );
}
