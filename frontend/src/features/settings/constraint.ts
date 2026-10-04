import type { JsonSchemaProperty } from "@/lib/json-schema";

export type IntegerDraftReason =
  | "empty"
  | "not_integer"
  | "below_min"
  | "above_max";

export type IntegerDraftValidity =
  | { ok: true; value: number }
  | { ok: false; reason: IntegerDraftReason };

export function admitIntegerDraft(
  draft: number | string,
  constraint: JsonSchemaProperty,
): IntegerDraftValidity {
  if (draft === "") {
    return { ok: false, reason: "empty" };
  }
  if (typeof draft !== "number" || !Number.isInteger(draft)) {
    return { ok: false, reason: "not_integer" };
  }
  if (typeof constraint.minimum === "number" && draft < constraint.minimum) {
    return { ok: false, reason: "below_min" };
  }
  if (typeof constraint.maximum === "number" && draft > constraint.maximum) {
    return { ok: false, reason: "above_max" };
  }
  return { ok: true, value: draft };
}

export function integerFallback(
  stored: unknown,
  constraint: JsonSchemaProperty,
  seed: unknown,
): number | null {
  if (stored === null || stored === undefined) {
    return typeof seed === "number" && Number.isInteger(seed) ? seed : null;
  }
  if (typeof stored !== "number" || !Number.isInteger(stored)) {
    return typeof seed === "number" && Number.isInteger(seed) ? seed : null;
  }
  if (typeof constraint.minimum === "number" && stored < constraint.minimum) {
    return constraint.minimum;
  }
  if (typeof constraint.maximum === "number" && stored > constraint.maximum) {
    return constraint.maximum;
  }
  return stored;
}

export function storedIntegerViolatesConstraint(
  stored: unknown,
  constraint: JsonSchemaProperty,
): boolean {
  if (typeof stored !== "number" || !Number.isInteger(stored)) {
    return stored !== null && stored !== undefined;
  }
  if (typeof constraint.minimum === "number" && stored < constraint.minimum) {
    return true;
  }
  if (typeof constraint.maximum === "number" && stored > constraint.maximum) {
    return true;
  }
  return false;
}

export function isStringEnum(constraint: JsonSchemaProperty): boolean {
  return Array.isArray(constraint.enum) && constraint.enum.length > 0;
}

/** True when the enum search text is not empty, not the selected value, and not an allowed choice. */
export function enumSearchMissesCatalog(
  search: string,
  selected: string,
  allowed: readonly string[] | undefined,
): boolean {
  if (search === "" || search === selected) {
    return false;
  }
  return !allowed?.includes(search);
}

export function admitEnumDraft(
  draft: number | string,
  constraint: JsonSchemaProperty,
): string | null {
  if (
    typeof draft === "string" &&
    draft !== "" &&
    constraint.enum?.includes(draft)
  ) {
    return draft;
  }
  return null;
}

export function dirtyParameterValues(
  parameters: Array<{
    key: string;
    value: unknown;
    constraint: JsonSchemaProperty;
  }>,
  drafts: Record<string, number | string>,
): Record<string, number | string> {
  const values: Record<string, number | string> = {};
  for (const item of parameters) {
    if (isStringEnum(item.constraint)) {
      const admitted = admitEnumDraft(drafts[item.key] ?? "", item.constraint);
      if (admitted !== null && admitted !== item.value) {
        values[item.key] = admitted;
      }
      continue;
    }
    const admitted = admitIntegerDraft(drafts[item.key] ?? "", item.constraint);
    if (!admitted.ok) {
      continue;
    }
    if (admitted.value !== item.value) {
      values[item.key] = admitted.value;
    }
  }
  return values;
}

