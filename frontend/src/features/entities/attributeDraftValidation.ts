import {
  ATTRIBUTE_NAME_MAX_LEN,
  attributeNameError,
  type AttributeNameErrorReason,
} from "@/features/entities/attributeNameValidation";
import type { AttributeDraft } from "@/features/entities/types";

export const STRING_MAX_LENGTH_MIN = 1;
export const STRING_MAX_LENGTH_MAX = 65535;
export const DECIMAL_PRECISION_MIN = 1;
export const DECIMAL_PRECISION_MAX = 1000;

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

function stringIssues(draft: AttributeDraft): AttributeIssue[] {
  const parsed = strictInt(draft.max_length);
  if (parsed == null) {
    return draft.max_length.trim() === ""
      ? [
          {
            field: "max_length",
            key: "entities.validation.attribute.maxLengthRequired",
          },
        ]
      : [
          {
            field: "max_length",
            key: "entities.validation.attribute.maxLengthRange",
            values: { min: STRING_MAX_LENGTH_MIN, max: STRING_MAX_LENGTH_MAX },
          },
        ];
  }
  if (parsed < STRING_MAX_LENGTH_MIN || parsed > STRING_MAX_LENGTH_MAX) {
    return [
      {
        field: "max_length",
        key: "entities.validation.attribute.maxLengthRange",
        values: { min: STRING_MAX_LENGTH_MIN, max: STRING_MAX_LENGTH_MAX },
      },
    ];
  }
  return [];
}

function decimalIssues(draft: AttributeDraft): AttributeIssue[] {
  const issues: AttributeIssue[] = [];
  const precisionText = draft.precision.trim();
  const scaleText = draft.scale.trim();
  const precision = strictInt(draft.precision);
  const scale = strictInt(draft.scale);
  if (precisionText === "") {
    issues.push({
      field: "precision",
      key: "entities.validation.attribute.precisionRequired",
    });
  } else if (
    precision == null ||
    precision < DECIMAL_PRECISION_MIN ||
    precision > DECIMAL_PRECISION_MAX
  ) {
    issues.push({
      field: "precision",
      key: "entities.validation.attribute.precisionRange",
      values: { min: DECIMAL_PRECISION_MIN, max: DECIMAL_PRECISION_MAX },
    });
  }
  if (scaleText === "") {
    issues.push({
      field: "scale",
      key: "entities.validation.attribute.scaleRequired",
    });
  } else if (scale == null || precision == null || scale > precision) {
    issues.push({
      field: "scale",
      key: "entities.validation.attribute.scaleRange",
    });
  }
  return issues;
}

function dictionaryIssues(draft: AttributeDraft): AttributeIssue[] {
  if (draft.dictionary_id.trim() !== "") return [];
  return [
    {
      field: "dictionary_id",
      key: "entities.validation.attribute.dictionaryRequired",
    },
  ];
}

function referenceIssues(draft: AttributeDraft): AttributeIssue[] {
  if (draft.target_entity_id.trim() !== "") return [];
  return [
    {
      field: "target_entity_id",
      key: "entities.validation.attribute.targetRequired",
    },
  ];
}

/** Issues for one draft. `names` includes this draft's name. */
export function attributeDraftIssues(
  draft: AttributeDraft,
  names: readonly string[],
): AttributeIssue[] {
  const issues: AttributeIssue[] = [];
  const name = nameIssue(draft, names);
  if (name) issues.push(name);
  if (draft.type === "string") issues.push(...stringIssues(draft));
  if (draft.type === "decimal") issues.push(...decimalIssues(draft));
  if (draft.type === "dictionary") issues.push(...dictionaryIssues(draft));
  if (draft.type === "reference") issues.push(...referenceIssues(draft));
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
