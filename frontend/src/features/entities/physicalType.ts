import type { AttributeDraft, AttributeType } from "@/features/entities/types";

/**
 * Postgres column type shown for an attribute draft.
 * Matches backend/entity/ddl.py `_physical_type` (type token only, not CHECK).
 */
const FIXED_COLUMN_TYPE: Record<
  Exclude<AttributeType, "string" | "decimal">,
  string
> = {
  text: "TEXT",
  integer: "BIGINT",
  number: "DOUBLE PRECISION",
  boolean: "BOOLEAN",
  date: "DATE",
  timestamp: "TIMESTAMPTZ",
  time: "TIME",
  json: "JSONB",
  dictionary: "VARCHAR(64)",
  reference: "BIGINT",
};

function strictInt(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export function physicalColumnType(
  attr: Pick<AttributeDraft, "type" | "max_length" | "precision" | "scale">,
): string {
  if (attr.type === "string") {
    const length = strictInt(attr.max_length);
    return length == null ? "VARCHAR" : `VARCHAR(${length})`;
  }
  if (attr.type === "decimal") {
    const precision = strictInt(attr.precision);
    const scale = strictInt(attr.scale);
    if (precision == null || scale == null) return "NUMERIC";
    return `NUMERIC(${precision},${scale})`;
  }
  return FIXED_COLUMN_TYPE[attr.type];
}
