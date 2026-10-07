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

export const GRANT_ACTIONS = ["read", "write", "export", "mcp_query"] as const;

export const MASK_KINDS = [
  "partial",
  "email",
  "hash",
  "truncate_date",
  "bucket",
  "redact",
  "null",
] as const;

export const RULE_OPS: readonly RuleOp[] = [
  "eq",
  "ne",
  "lt",
  "lte",
  "gt",
  "gte",
  "in",
  "is_null",
  "contains",
];

const TIME_ATTRIBUTE_TYPES = new Set(["date", "timestamp"]);
const ORDER_OPS = new Set<RuleOp>(["lt", "lte", "gt", "gte"]);

export type RuleOperandKind = RuleOperand["kind"];

/** Operand choices the row-rule editor may offer for this comparison and column type. */
export function ruleOperandKinds(
  op: RuleOp,
  attributeType: string | null,
): RuleOperandKind[] {
  const kinds: RuleOperandKind[] = ["value"];
  if (op === "in") kinds.push("subject_attr");
  if ((op === "eq" || op === "ne") && attributeType === "user") kinds.push("subject_id");
  if (
    ORDER_OPS.has(op) &&
    attributeType != null &&
    TIME_ATTRIBUTE_TYPES.has(attributeType)
  ) {
    kinds.push("rel_time");
  }
  return kinds;
}

/** One hint for an operand this column could use, hidden by the current comparison. */
export function ruleEditorHint(op: RuleOp, attributeType: string | null): string | null {
  if (op !== "in") return "entities.access.rule.hint.subjectAttr";
  if (attributeType === "user") return "entities.access.rule.hint.subjectId";
  if (attributeType != null && TIME_ATTRIBUTE_TYPES.has(attributeType)) {
    return "entities.access.rule.hint.relTime";
  }
  return null;
}

const RULE_REJECTION_KEYS: readonly { needle: string; key: string }[] = [
  {
    needle: "subject_attr is only valid for in",
    key: "entities.access.rule.reject.subjectAttr",
  },
  {
    needle: "subject_id is true and only eq or ne",
    key: "entities.access.rule.reject.subjectIdOp",
  },
  {
    needle: "subject_id compares only a user attribute",
    key: "entities.access.rule.reject.subjectIdType",
  },
  {
    needle: "rel_time is only valid for lt, lte, gt, and gte",
    key: "entities.access.rule.reject.relTimeOp",
  },
  {
    needle: "rel_time compares only date or timestamp",
    key: "entities.access.rule.reject.relTimeType",
  },
];

/** Locale key for a row-rule `detail`, or null when the detail is not a rule path. */
export function ruleRejectionKey(detail: string): string | null {
  const match = RULE_REJECTION_KEYS.find((item) => detail.includes(item.needle));
  if (match) return match.key;
  if (detail.startsWith("$")) return "entities.access.rule.reject.generic";
  return null;
}

export type StoredLeaf = {
  op: RuleOp;
  attributeId: string;
  operand: RuleOperand;
};

export type ParsedRule =
  | { kind: "all" }
  | { kind: "leaves"; leaves: StoredLeaf[] }
  | { kind: "custom" };

/** Show the combination budget when usage is near the cap, over it, or a subject is over its own cap. */
export function combinationBudgetVisible(views: {
  combinations: number;
  combination_limit: number;
  subjects_over_limit: number;
}): boolean {
  if (views.subjects_over_limit > 0) return true;
  if (views.combinations > views.combination_limit) return true;
  if (views.combination_limit <= 0) return false;
  return views.combinations * 5 >= views.combination_limit * 4;
}

export function viewsNeedAttention(input: {
  head_version_id: string | null;
  views: { state: "ready" | "pending" | "failed" };
}): boolean {
  if (input.head_version_id == null) return true;
  return input.views.state !== "ready";
}

export function isAccessKey(value: string): boolean {
  return LEVEL_KEY.test(value);
}

export function ladderIssueKey(issue: string): string {
  if (issue === "first") return "entities.access.ladders.invalid.first";
  if (issue === "key") return "entities.access.ladders.invalid.key";
  if (issue === "duplicate") return "entities.access.ladders.invalid.duplicate";
  if (issue === "extra_clear") return "entities.access.ladders.invalid.extraClear";
  return "entities.access.ladders.invalid";
}

export function levelModeKind(mode: "clear" | { type: string }): string {
  return mode === "clear" ? "clear" : mode.type;
}

/** Clear stays a mask name. Every other level keeps its key so two masks of one kind stay distinct. */
export function levelOptionLabel(maskName: string, key: string): string {
  if (key === "clear") return maskName;
  return `${maskName} (${key})`;
}

export function profileIsAllClear(
  columns: { attribute_id: string; level: string }[],
  attributeIds: readonly string[],
): boolean {
  if (attributeIds.length === 0) return false;
  const chosen = new Map(columns.map((column) => [column.attribute_id, column.level]));
  return attributeIds.every((id) => chosen.get(id) === "clear");
}

export type AccessSectionId = "ladders" | "profiles" | "grants" | "restrictions";

export type AccessChainStep = {
  id: AccessSectionId;
  emphasis: boolean;
};

export type AccessGuide =
  | { kind: "no_attributes" }
  | { kind: "seed_only" }
  | { kind: "unused_profiles"; names: string[] }
  | { kind: "none" };

/** True when every published column still has only the full-text level. */
export function laddersClearOnly(ladders: { levels: { key: string }[] }[]): boolean {
  return (
    ladders.length > 0 &&
    ladders.every(
      (ladder) =>
        ladder.levels.length > 0 && ladder.levels.every((level) => level.key === "clear"),
    )
  );
}

export function profileGrantCount(
  profileId: string,
  grants: { profile_id: string }[],
): number {
  return grants.reduce((count, grant) => (grant.profile_id === profileId ? count + 1 : count), 0);
}

/** A display name that can become an access key. Empty when the name has no usable letters. */
export function accessKeyFromName(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_");
  if (!slug) return "";
  const keyed = (/^[a-z]/.test(slug) ? slug : `p_${slug}`).slice(0, 63);
  return isAccessKey(keyed) ? keyed : "";
}

/** The first unfinished step is emphasized. Restrictions stay in the chain as an override, never as the next required step. */
export function accessChainSteps(input: {
  ladderCount: number;
  profileCount: number;
  grantCount: number;
}): AccessChainStep[] {
  const current: AccessSectionId | null =
    input.ladderCount === 0
      ? "ladders"
      : input.profileCount === 0
        ? "profiles"
        : input.grantCount === 0
          ? "grants"
          : null;
  return [
    { id: "ladders", emphasis: current === "ladders" },
    { id: "profiles", emphasis: current === "profiles" },
    { id: "grants", emphasis: current === "grants" },
    { id: "restrictions", emphasis: false },
  ];
}

/**
 * One next step for a first visit.
 * A second scheme, a vaguer level, or any restriction means the author has started, so the tutorial hides.
 */
export function accessGuide(input: {
  ladders: { levels: { key: string }[] }[];
  profiles: { id: string; name: string }[];
  grants: { profile_id: string }[];
  restrictionCount: number;
}): AccessGuide {
  if (input.ladders.length === 0) return { kind: "no_attributes" };
  const hasNonClear = input.ladders.some((ladder) =>
    ladder.levels.some((level) => level.key !== "clear"),
  );
  if (input.profiles.length >= 2 || hasNonClear || input.restrictionCount > 0) {
    return { kind: "none" };
  }
  const unused = input.profiles
    .filter((profile) => profileGrantCount(profile.id, input.grants) === 0)
    .map((profile) => profile.name);
  if (unused.length > 0) return { kind: "unused_profiles", names: unused };
  if (input.grants.length === 1 && input.profiles.length === 1) return { kind: "seed_only" };
  return { kind: "none" };
}

export function sameProfileColumns(
  attributeIds: string[],
  saved: { attribute_id: string; level: string }[],
  draft: Record<string, string>,
): boolean {
  const next = columnsFromMatrix(attributeIds, draft);
  const previous = columnsFromMatrix(
    attributeIds,
    Object.fromEntries(saved.map((column) => [column.attribute_id, column.level])),
  );
  if (next.length !== previous.length) return false;
  return next.every(
    (column, index) =>
      column.attribute_id === previous[index]?.attribute_id &&
      column.level === previous[index]?.level,
  );
}

export function matrixFromProfiles(
  ladders: { attribute_id: string }[],
  profiles: { id: string; columns: { attribute_id: string; level: string }[] }[],
): Record<string, Record<string, string>> {
  const cells: Record<string, Record<string, string>> = {};
  for (const profile of profiles) {
    cells[profile.id] = {};
    for (const ladder of ladders) {
      cells[profile.id][ladder.attribute_id] = matrixColumn(ladder.attribute_id, profile.columns);
    }
  }
  return cells;
}

export function levelReferrers(
  profiles: { name: string; columns: { attribute_id: string; level: string }[] }[],
  restrictions: { ceilings: { attribute_id: string; level: string }[] }[],
  attributeId: string,
  levelKey: string,
): { profileNames: string[]; restrictionCount: number } {
  const profileNames = profiles
    .filter((profile) =>
      profile.columns.some(
        (column) => column.attribute_id === attributeId && column.level === levelKey,
      ),
    )
    .map((profile) => profile.name);
  const restrictionCount = restrictions.filter((item) =>
    item.ceilings.some(
      (ceiling) => ceiling.attribute_id === attributeId && ceiling.level === levelKey,
    ),
  ).length;
  return { profileNames, restrictionCount };
}

export function ruleOpLabelKey(op: RuleOp, attributeType: string | null | undefined): string {
  if (attributeType && TIME_ATTRIBUTE_TYPES.has(attributeType) && ORDER_OPS.has(op)) {
    return `entities.access.rule.op.${op}.time`;
  }
  return `entities.access.rule.op.${op}`;
}

type Label = (key: string, options?: Record<string, unknown>) => string;

export function describeStoredRule(
  t: Label,
  rule: Record<string, unknown> | null,
  names: {
    attributeName: (id: string) => string;
    attributeType: (id: string) => string | null;
  },
): string {
  const parsed = parseStoredRule(rule);
  if (parsed.kind === "all") return t("entities.access.grants.allRows");
  if (parsed.kind === "custom") return t("entities.access.grants.customRule");
  return parsed.leaves
    .map((leaf) =>
      ruleLeafPhrase({
        attribute: names.attributeName(leaf.attributeId),
        operator: t(ruleOpLabelKey(leaf.op, names.attributeType(leaf.attributeId))),
        operand:
          leaf.operand.kind === "subject_id"
            ? t("entities.access.rule.subjectId")
            : operandText(leaf.operand),
      }),
    )
    .join(` ${t("entities.access.summary.and")} `);
}

export function formatGrantLine(
  t: Label,
  input: {
    subject: string;
    profileName: string;
    actions: string[];
    broken: boolean;
    rowRule: Record<string, unknown> | null;
    columns: { attribute_id: string; level: string }[];
    attributeIds: readonly string[];
    attributeName: (id: string) => string;
    attributeType: (id: string) => string | null;
  },
): string {
  const scope = profileIsAllClear(input.columns, input.attributeIds)
    ? t("entities.access.summary.allClear")
    : input.profileName;
  const actions = input.actions
    .map((action) => t(`entities.access.action.${action}`))
    .join(t("entities.access.summary.actionJoin"));
  const rows = describeStoredRule(t, input.rowRule, {
    attributeName: input.attributeName,
    attributeType: input.attributeType,
  });
  const base = `${input.subject} · ${scope} · ${actions} · ${rows}`;
  return input.broken ? `${base} · ${t("entities.access.broken")}` : base;
}

export function ruleLeafPhrase(parts: {
  attribute: string;
  operator: string;
  operand: string;
}): string {
  return `${parts.attribute} ${parts.operator} ${parts.operand}`.replace(/\s+/g, " ").trim();
}

export function parseStoredRule(rule: Record<string, unknown> | null): ParsedRule {
  if (rule == null) return { kind: "all" };
  if (Array.isArray(rule.and)) {
    if (rule.and.length === 0) return { kind: "all" };
    const leaves: StoredLeaf[] = [];
    for (const node of rule.and) {
      const leaf = parseLeafRecord(node);
      if (!leaf) return { kind: "custom" };
      leaves.push(leaf);
    }
    return { kind: "leaves", leaves };
  }
  const single = parseLeafRecord(rule);
  if (single) return { kind: "leaves", leaves: [single] };
  return { kind: "custom" };
}

function parseLeafRecord(node: unknown): StoredLeaf | null {
  if (typeof node !== "object" || node === null || Array.isArray(node)) return null;
  const entries = Object.entries(node as Record<string, unknown>);
  if (entries.length !== 1) return null;
  const [op, body] = entries[0] ?? [];
  if (typeof op !== "string" || !isRuleOp(op)) return null;
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.attr !== "string") return null;
  const operand = parseOperand(record);
  if (!operand) return null;
  return { op, attributeId: record.attr, operand };
}

function parseOperand(body: Record<string, unknown>): RuleOperand | null {
  const present = (["value", "subject_attr", "subject_id", "rel_time"] as const).filter(
    (key) => key in body,
  );
  if (present.length !== 1) return null;
  const kind = present[0];
  if (kind === "value") return { kind: "value", value: body.value };
  if (kind === "subject_attr") {
    return typeof body.subject_attr === "string"
      ? { kind: "subject_attr", key: body.subject_attr }
      : null;
  }
  if (kind === "subject_id") return body.subject_id === true ? { kind: "subject_id" } : null;
  return typeof body.rel_time === "string" ? { kind: "rel_time", duration: body.rel_time } : null;
}

function isRuleOp(value: string): value is RuleOp {
  return (RULE_OPS as readonly string[]).includes(value);
}

export function operandText(
  operand: Exclude<RuleOperand, { kind: "subject_id" }>,
): string {
  if (operand.kind === "value") {
    const value = operand.value;
    if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
    if (value == null) return "";
    return String(value);
  }
  if (operand.kind === "subject_attr") return operand.key;
  return operand.duration;
}
