/** Pure access-control Console rules. No network, no React. */

export const LEVEL_KEY = /^[a-z][a-z0-9_]{0,62}$/;

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

export type RuleNode =
  | { kind: "and" | "or"; children: RuleNode[] }
  | { kind: "not"; child: RuleNode }
  | { kind: "leaf"; op: RuleOp; attributeId: string; operand: RuleOperand };

export type AccessProblem =
  | "pending"
  | "write_denied"
  | "conflict"
  | "combination_limit"
  | "other";

export type CellMark = "masked" | "row_varying";

export type PresentedCell = {
  kind: "value" | "withheld" | "empty" | "inaccessible_record";
  text: string;
  marks: CellMark[];
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

export function emptyRule(): RuleNode {
  return { kind: "and", children: [] };
}

/** The Console editor starts from an empty AND and only appends leaves. */
export function appendEditorCondition(current: RuleNode, leaf: RuleNode): RuleNode {
  if (current.kind === "and" || current.kind === "or") {
    return { kind: current.kind, children: [...current.children, leaf] };
  }
  return { kind: "and", children: [current, leaf] };
}

export function serializeRule(node: RuleNode): Record<string, unknown> | null {
  if (node.kind === "and" || node.kind === "or") {
    if (node.children.length === 0) return null;
    return { [node.kind]: node.children.map((child) => serializeRule(child) ?? true) };
  }
  if (node.kind === "not") {
    const child = serializeRule(node.child);
    return child ? { not: child } : null;
  }
  const body: Record<string, unknown> = { attr: node.attributeId };
  const operand = node.operand;
  if (operand.kind === "value") body.value = operand.value;
  if (operand.kind === "subject_attr") body.subject_attr = operand.key;
  if (operand.kind === "subject_id") body.subject_id = true;
  if (operand.kind === "rel_time") body.rel_time = operand.duration;
  return { [node.op]: body };
}

export function parseRule(raw: unknown): RuleNode | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const entries = Object.entries(raw as Record<string, unknown>);
  if (entries.length !== 1) return null;
  const [op, body] = entries[0] as [string, unknown];
  if (op === "and" || op === "or") {
    if (!Array.isArray(body)) return null;
    const children = body.map(parseRule).filter((item): item is RuleNode => item !== null);
    return { kind: op, children };
  }
  if (op === "not") {
    const child = parseRule(body);
    return child ? { kind: "not", child } : null;
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const leaf = body as Record<string, unknown>;
  if (typeof leaf.attr !== "string") return null;
  let operand: RuleOperand = { kind: "value", value: leaf.value };
  if (typeof leaf.subject_attr === "string") {
    operand = { kind: "subject_attr", key: leaf.subject_attr };
  } else if (leaf.subject_id === true) {
    operand = { kind: "subject_id" };
  } else if (typeof leaf.rel_time === "string") {
    operand = { kind: "rel_time", duration: leaf.rel_time };
  }
  return { kind: "leaf", op: op as RuleOp, attributeId: leaf.attr, operand };
}

export function ruleUsesFreeText(_node: RuleNode): boolean {
  return false;
}

export function combinationOverLimit(views: {
  combinations: number;
  combination_limit: number;
  subjects_over_limit: number;
}): boolean {
  return views.subjects_over_limit > 0 || views.combinations > views.combination_limit;
}

export function classifyAccessProblem(code: string | null | undefined): AccessProblem {
  if (code === "ENTITY_ACCESS_PENDING") return "pending";
  if (code === "ENTITY_ACCESS_WRITE_DENIED") return "write_denied";
  if (code === "ENTITY_ROW_CONFLICT") return "conflict";
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
  masked: boolean;
  rowVarying: boolean;
  referenceHidden: boolean;
}): PresentedCell {
  const marks: CellMark[] = [];
  if (input.masked) marks.push("masked");
  if (input.rowVarying) marks.push("row_varying");
  const withheld = input.withheld ?? [];
  if (withheld.includes(input.name)) {
    return { kind: "withheld", text: "", marks };
  }
  if (input.value == null || input.value === "") {
    return { kind: "empty", text: "", marks };
  }
  if (input.referenceHidden) {
    return { kind: "inaccessible_record", text: "", marks };
  }
  return { kind: "value", text: String(input.value), marks };
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
