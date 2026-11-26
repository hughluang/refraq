export type OperatorArity = "none" | "scalar" | "range" | "array";
export type OperatorValueDomain = "field" | "string" | "json";

export type FilterOperatorMeta = {
  name: string;
  arity: OperatorArity;
  valueDomain: OperatorValueDomain;
  labelKey: string;
};

export const ORDERED_FILTER_OPERATORS = [
  "eq",
  "ne",
  "ieq",
  "contains",
  "not_contains",
  "starts_with",
  "ends_with",
  "gt",
  "gte",
  "lt",
  "lte",
  "between",
  "in",
  "not_in",
  "is_null",
  "is_not_null",
  "json_contains",
  "has_key",
  "has_any_keys",
  "has_all_keys",
] as const;

const METAS: Record<string, FilterOperatorMeta> = {
  eq: { name: "eq", arity: "scalar", valueDomain: "field", labelKey: "filter.op.eq" },
  ne: { name: "ne", arity: "scalar", valueDomain: "field", labelKey: "filter.op.ne" },
  ieq: { name: "ieq", arity: "scalar", valueDomain: "string", labelKey: "filter.op.ieq" },
  contains: {
    name: "contains",
    arity: "scalar",
    valueDomain: "string",
    labelKey: "filter.op.contains",
  },
  not_contains: {
    name: "not_contains",
    arity: "scalar",
    valueDomain: "string",
    labelKey: "filter.op.not_contains",
  },
  starts_with: {
    name: "starts_with",
    arity: "scalar",
    valueDomain: "string",
    labelKey: "filter.op.starts_with",
  },
  ends_with: {
    name: "ends_with",
    arity: "scalar",
    valueDomain: "string",
    labelKey: "filter.op.ends_with",
  },
  gt: { name: "gt", arity: "scalar", valueDomain: "field", labelKey: "filter.op.gt" },
  gte: { name: "gte", arity: "scalar", valueDomain: "field", labelKey: "filter.op.gte" },
  lt: { name: "lt", arity: "scalar", valueDomain: "field", labelKey: "filter.op.lt" },
  lte: { name: "lte", arity: "scalar", valueDomain: "field", labelKey: "filter.op.lte" },
  between: {
    name: "between",
    arity: "range",
    valueDomain: "field",
    labelKey: "filter.op.between",
  },
  in: { name: "in", arity: "array", valueDomain: "field", labelKey: "filter.op.in" },
  not_in: { name: "not_in", arity: "array", valueDomain: "field", labelKey: "filter.op.not_in" },
  is_null: {
    name: "is_null",
    arity: "none",
    valueDomain: "field",
    labelKey: "filter.op.is_null",
  },
  is_not_null: {
    name: "is_not_null",
    arity: "none",
    valueDomain: "field",
    labelKey: "filter.op.is_not_null",
  },
  json_contains: {
    name: "json_contains",
    arity: "scalar",
    valueDomain: "json",
    labelKey: "filter.op.json_contains",
  },
  has_key: {
    name: "has_key",
    arity: "scalar",
    valueDomain: "string",
    labelKey: "filter.op.has_key",
  },
  has_any_keys: {
    name: "has_any_keys",
    arity: "array",
    valueDomain: "string",
    labelKey: "filter.op.has_any_keys",
  },
  has_all_keys: {
    name: "has_all_keys",
    arity: "array",
    valueDomain: "string",
    labelKey: "filter.op.has_all_keys",
  },
};

export function getFilterOperatorMeta(op: string): FilterOperatorMeta {
  return (
    METAS[op] ?? {
      name: op,
      arity: "scalar",
      valueDomain: "field",
      labelKey: `filter.op.${op}`,
    }
  );
}

export function filterOperatorLabelKey(op: string): string {
  return getFilterOperatorMeta(op).labelKey;
}

export function availableFilterOperators(allowed?: readonly string[] | null): string[] {
  if (!allowed || allowed.length === 0) return [];
  const allowedSet = new Set(allowed);
  const ordered = ORDERED_FILTER_OPERATORS.filter((op) => allowedSet.has(op));
  const extras = allowed.filter(
    (op) => !(ORDERED_FILTER_OPERATORS as readonly string[]).includes(op),
  );
  return [...ordered, ...extras];
}

export function transitionOperatorValues(
  prevOp: string,
  nextOp: string,
  currentValues: readonly string[],
): string[] {
  const prevMeta = getFilterOperatorMeta(prevOp);
  const nextMeta = getFilterOperatorMeta(nextOp);
  if (nextMeta.arity === "none") return [];
  if (prevMeta.valueDomain !== nextMeta.valueDomain) {
    if (nextMeta.arity === "range") return ["", ""];
    return [""];
  }
  if (nextMeta.arity === "range") {
    return [currentValues[0] ?? "", currentValues[1] ?? ""];
  }
  if (nextMeta.arity === "array") {
    const kept = currentValues.filter((v) => v !== "");
    return kept.length > 0 ? kept : [""];
  }
  return [currentValues[0] ?? ""];
}
