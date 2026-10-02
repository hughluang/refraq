import {
  ATTRIBUTE_NAME_MAX_LEN,
  attributeNameError,
  type AttributeNameErrorReason,
} from "@/features/entities/attributeNameValidation";
import { ATTRIBUTE_TYPE_CATALOG } from "@/features/entities/attributeTypes.generated";
import type { AttributeDraft, AttributeType } from "@/features/entities/types";

export type AttributeIssueField =
  | "name"
  | "max_length"
  | "precision"
  | "scale"
  | "dictionary_id"
  | "target_entity_id";

export type AttributeIssue = {
  field: AttributeIssueField;
  key: string;
  values?: Record<string, string | number>;
};

const NAME_KEYS: Record<AttributeNameErrorReason, string> = {
  required: "entities.validation.attributeName.required",
  charset: "entities.validation.attributeName.charset",
  tooLong: "entities.validation.attributeName.tooLong",
  reserved: "entities.validation.attributeName.reserved",
  duplicate: "entities.validation.attributeName.duplicate",
};

function strictInt(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function nameIssue(draft: AttributeDraft, names: readonly string[]): AttributeIssue | null {
  const reason = attributeNameError(draft.name, names);
  if (!reason) return null;
  if (reason === "tooLong") {
    return {
      field: "name",
      key: NAME_KEYS.tooLong,
      values: { max: ATTRIBUTE_NAME_MAX_LEN },
    };
  }
  if (reason === "required") {
    return { field: "name", key: NAME_KEYS.required };
  }
  return {
    field: "name",
    key: NAME_KEYS[reason],
    values: { name: draft.name.trim() },
  };
}

type ConfigIssueField = Exclude<AttributeIssueField, "name">;

type IntIssueField = "max_length" | "precision" | "scale";

const REQUIRED_KEY: Record<ConfigIssueField, string> = {
  max_length: "entities.validation.attribute.maxLengthRequired",
  precision: "entities.validation.attribute.precisionRequired",
  scale: "entities.validation.attribute.scaleRequired",
  dictionary_id: "entities.validation.attribute.dictionaryRequired",
  target_entity_id: "entities.validation.attribute.targetRequired",
};

const RANGE_KEY: Record<IntIssueField, string> = {
  max_length: "entities.validation.attribute.maxLengthRange",
  precision: "entities.validation.attribute.precisionRange",
  scale: "entities.validation.attribute.scaleRange",
};

type CatalogField =
  | {
      readonly kind: "int";
      readonly minimum: number;
      readonly maximum: number;
      readonly atMost: string | null;
    }
  | { readonly kind: "string" };

function draftConfigText(draft: AttributeDraft, field: ConfigIssueField): string {
  switch (field) {
    case "max_length":
      return draft.max_length;
    case "precision":
      return draft.precision;
    case "scale":
      return draft.scale;
    case "dictionary_id":
      return draft.dictionary_id;
    case "target_entity_id":
      return draft.target_entity_id;
  }
}

function catalogFields(type: AttributeType): Array<[ConfigIssueField, CatalogField]> {
  const config = ATTRIBUTE_TYPE_CATALOG[type].config as Readonly<
    Record<string, CatalogField>
  >;
  return Object.entries(config) as Array<[ConfigIssueField, CatalogField]>;
}

function configIssues(draft: AttributeDraft): AttributeIssue[] {
  const issues: AttributeIssue[] = [];
  for (const [name, field] of catalogFields(draft.type)) {
    const text = draftConfigText(draft, name).trim();
    if (field.kind === "string") {
      if (text === "") {
        issues.push({ field: name, key: REQUIRED_KEY[name] });
      }
      continue;
    }
    const intName = name as IntIssueField;
    const parsed = strictInt(draftConfigText(draft, intName));
    if (text === "") {
      issues.push({ field: intName, key: REQUIRED_KEY[intName] });
      continue;
    }
    const rangeKey = RANGE_KEY[intName];
    if (field.atMost === "precision") {
      const bound = strictInt(draftConfigText(draft, "precision"));
      if (parsed == null || bound == null || parsed > bound) {
        issues.push({ field: intName, key: rangeKey });
      }
      continue;
    }
    if (parsed == null || parsed < field.minimum || parsed > field.maximum) {
      issues.push({
        field: intName,
        key: rangeKey,
        values: { min: field.minimum, max: field.maximum },
      });
    }
  }
  return issues;
}

/** Issues for one draft. `names` includes this draft's name. */
export function attributeDraftIssues(
  draft: AttributeDraft,
  names: readonly string[],
): AttributeIssue[] {
  const issues: AttributeIssue[] = [];
  const name = nameIssue(draft, names);
  if (name) issues.push(name);
  issues.push(...configIssues(draft));
  return issues;
}

export type AttributeConfigFact =
  | { kind: "max_length"; value: string }
  | { kind: "decimal"; precision: string; scale: string }
  | { kind: "dictionary"; label: string };

/** Type configuration for the attribute list. Null when the type has no config, or the config is blank. */
export function attributeConfigSummary(
  draft: AttributeDraft,
): AttributeConfigFact | null {
  if (draft.type === "string") {
    const value = draft.max_length.trim();
    return value ? { kind: "max_length", value } : null;
  }
  if (draft.type === "decimal") {
    const precision = draft.precision.trim();
    const scale = draft.scale.trim();
    if (!precision || !scale) return null;
    return { kind: "decimal", precision, scale };
  }
  if (draft.type === "dictionary") {
    const label =
      draft.dictionary_display_name.trim() ||
      draft.dictionary_name.trim() ||
      draft.dictionary_id.trim();
    if (!label) return null;
    return { kind: "dictionary", label };
  }
  return null;
}

export function attributeIndexFromPath(path: string): number | null {
  const match = /^attributes\.(\d+)\./.exec(path);
  return match ? Number(match[1]) : null;
}

export function firstAttributeErrorIndex(
  errors: Record<string, unknown>,
): number | null {
  let first: number | null = null;
  for (const [key, value] of Object.entries(errors)) {
    if (value == null || value === false || value === "") continue;
    const index = attributeIndexFromPath(key);
    if (index == null) continue;
    if (first == null || index < first) first = index;
  }
  return first;
}
