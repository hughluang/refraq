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

export function dirtyIntegerValues(
  parameters: Array<{
    key: string;
    value: unknown;
    constraint: JsonSchemaProperty;
  }>,
  drafts: Record<string, number | string>,
): Record<string, number> {
  const values: Record<string, number> = {};
  for (const item of parameters) {
    const admitted = admitIntegerDraft(
      drafts[item.key] ?? "",
      item.constraint,
    );
    if (!admitted.ok) {
      continue;
    }
    if (admitted.value !== item.value) {
      values[item.key] = admitted.value;
    }
  }
  return values;
}
