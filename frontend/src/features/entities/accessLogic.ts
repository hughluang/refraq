/** Pure access-control Console rules. No network, no React. */

const LEVEL_KEY = /^[a-z][a-z0-9_]{0,62}$/;

export type MaskMode =
  | "clear"
  | { type: "partial"; keep_first: number; keep_last: number }
  | { type: "email" }
  | { type: "hash" }
  | { type: "redact" }
  | { type: "null" }
  | { type: "truncate_date"; unit: "year" | "month" | "day" }
  | { type: "bucket"; width: number };

export type LadderLevel = { key: string; mode: MaskMode };

export type RuleOp =
  | "eq"
  | "ne"
  | "lt"
  | "lte"
  | "gt"
  | "gte"
  | "in"
  | "is_null"
  | "contains";

export type RuleOperand =
  | { kind: "value"; value: unknown }
  | { kind: "subject_attr"; key: string }
  | { kind: "subject_id" }
  | { kind: "rel_time"; duration: string };

export type RuleLeaf = {
  kind: "leaf";
  op: RuleOp;
  attributeId: string;
  operand: RuleOperand;
};

/** The Console editor only builds a flat AND of leaves. */
export type RuleNode = { kind: "and"; children: RuleLeaf[] };

export type AccessProblem =
  | "pending"
  | "combination_limit"
  | "other";

export type PresentedCell = {
  kind: "value" | "withheld" | "empty" | "inaccessible_record";
  text: string;
};

export function validateLadder(levels: LadderLevel[]): string | null {
  if (levels.length === 0) return "empty";
  const first = levels[0];
  if (!first || first.key !== "clear" || first.mode !== "clear") return "first";
  const seen = new Set<string>();
  for (const level of levels) {
    if (!LEVEL_KEY.test(level.key)) return "key";
    if (seen.has(level.key)) return "duplicate";
    seen.add(level.key);
    if (level.key !== "clear" && level.mode === "clear") return "extra_clear";
  }
  return null;
}

export function matrixColumn(
  attributeId: string,
  columns: { attribute_id: string; level: string }[],
): string {
  return columns.find((column) => column.attribute_id === attributeId)?.level ?? "";
}

export function columnsFromMatrix(
  attributeIds: string[],
  chosen: Record<string, string>,
): { attribute_id: string; level: string }[] {
  return attributeIds
    .filter((id) => chosen[id])
    .map((id) => ({ attribute_id: id, level: chosen[id] as string }));
}

export function appendEditorCondition(current: RuleNode, leaf: RuleLeaf): RuleNode {
  return { kind: "and", children: [...current.children, leaf] };
}

export function serializeRule(node: RuleNode): Record<string, unknown> | null {
  if (node.children.length === 0) return null;
  return { and: node.children.map(serializeLeaf) };
}

function serializeLeaf(node: RuleLeaf): Record<string, unknown> {
  const body: Record<string, unknown> = { attr: node.attributeId };
  const operand = node.operand;
  if (operand.kind === "value") body.value = operand.value;
  if (operand.kind === "subject_attr") body.subject_attr = operand.key;
  if (operand.kind === "subject_id") body.subject_id = true;
  if (operand.kind === "rel_time") body.rel_time = operand.duration;
  return { [node.op]: body };
}

/** No serving table is not "views are ready", even when generation state is ready. */
export function viewsStatusKey(input: {
  head_version_id: string | null;
  views: { state: "ready" | "pending" | "failed" };
}): string {
  if (input.head_version_id == null) return "entities.access.views.noHead";
  return `entities.access.views.${input.views.state}`;
}

export function classifyAccessProblem(code: string | null | undefined): AccessProblem {
  if (code === "ENTITY_ACCESS_PENDING") return "pending";
  if (code === "ENTITY_ACCESS_COMBINATION_LIMIT") return "combination_limit";
  return "other";
}

export function narrowBody(
  kind: "none" | "user" | "role" | "group",
  id: string,
): { narrow?: { type: string; id?: string } } {
  if (kind === "none") return {};
  if (kind === "user") return { narrow: { type: "user" } };
  return { narrow: { type: kind, id } };
}

export function presentCell(input: {
  name: string;
  value: unknown;
  withheld: readonly string[] | null;
  referenceHidden: boolean;
}): PresentedCell {
  const withheld = input.withheld ?? [];
  if (withheld.includes(input.name)) {
    return { kind: "withheld", text: "" };
  }
  if (input.value == null || input.value === "") {
    return { kind: "empty", text: "" };
  }
  if (input.referenceHidden) {
    return { kind: "inaccessible_record", text: "" };
  }
  return { kind: "value", text: String(input.value) };
}

export function isMaskedPresentation(levels: { mode: unknown }[] | undefined): boolean {
  if (!levels || levels.length === 0) return false;
  return levels.some((level) => level.mode !== "clear");
}

export function withheldNames(row: Record<string, unknown>, field: string | null): string[] {
  if (!field) return [];
  const raw = row[field];
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string");
}

export function literalOperand(op: RuleOp, raw: string): unknown {
  if (op === "is_null") return raw === "true";
  if (op === "in") {
    return raw
      .split(",")
      .map((part) => part.trim())
      .filter((part) => part.length > 0);
  }
  return raw;
}
