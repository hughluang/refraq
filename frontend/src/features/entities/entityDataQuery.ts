import type { DataAttribute, DataSchema } from "./accessTypes";
import { parseEntityDataJson } from "./entityDataJson";
import { availableFilterOperators, getFilterOperatorMeta } from "@/lib/filterOperators";
import { Instant } from "@/lib/instant";

export type QueryCondition = {
  field: string;
  op: string;
  values: string[];
  negate?: boolean;
};

export type QueryFilterGroup = {
  match: "all" | "any";
  conditions: QueryCondition[];
};

export type EntityDataQuery = {
  lookup: { field: string; value: string } | null;
  match: "all" | "any";
  conditions: QueryCondition[];
  groups?: QueryFilterGroup[];
};

export const EMPTY_DATA_QUERY: EntityDataQuery = { lookup: null, match: "all", conditions: [] };

export type DataFilter =
  | { field: string; op: string; value?: unknown }
  | { all: DataFilter[] }
  | { any: DataFilter[] }
  | { not: DataFilter };

const PARAM = "dataQuery";
const ERROR = "entities.data.query.error.";

function hasExactOrSubsetKeys(
  value: unknown,
  required: string[],
  optional: string[] = [],
): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  return (
    required.every((key) => Object.hasOwn(value, key)) && keys.every((key) => allowed.has(key))
  );
}

function isCondition(value: unknown): value is QueryCondition {
  if (!hasExactOrSubsetKeys(value, ["field", "op", "values"], ["negate"])) return false;
  if (value.negate !== undefined && typeof value.negate !== "boolean") return false;
  return (
    typeof value.field === "string" &&
    typeof value.op === "string" &&
    Array.isArray(value.values) &&
    value.values.every((item) => typeof item === "string")
  );
}

function isFilterGroup(value: unknown): value is QueryFilterGroup {
  if (!hasExactOrSubsetKeys(value, ["match", "conditions"])) return false;
  return (
    (value.match === "all" || value.match === "any") &&
    Array.isArray(value.conditions) &&
    value.conditions.every(isCondition)
  );
}

/** A malformed saved search must never turn into an unfiltered request. */
export function readDataQuery(params: Pick<URLSearchParams, "getAll">): EntityDataQuery | null {
  const encoded = params.getAll(PARAM);
  if (encoded.length === 0) return EMPTY_DATA_QUERY;
  if (encoded.length !== 1) return null;
  try {
    const parsed: unknown = JSON.parse(encoded[0]);
    if (!hasExactOrSubsetKeys(parsed, ["lookup", "match", "conditions"], ["groups"]))
      return null;
    const { lookup, match, conditions, groups } = parsed;
    if (
      lookup !== null &&
      !(
        hasExactOrSubsetKeys(lookup, ["field", "value"]) &&
        typeof lookup.field === "string" &&
        typeof lookup.value === "string"
      )
    )
      return null;
    if (
      (match !== "all" && match !== "any") ||
      !Array.isArray(conditions) ||
      !conditions.every(isCondition)
    )
      return null;
    if (groups !== undefined && (!Array.isArray(groups) || !groups.every(isFilterGroup))) {
      return null;
    }
    const result: EntityDataQuery = {
      lookup: lookup as EntityDataQuery["lookup"],
      match,
      conditions,
    };
    if (groups && groups.length > 0) result.groups = groups;
    return result;
  } catch {
    return null;
  }
}

export function writeDataQuery(params: URLSearchParams, query: EntityDataQuery): void {
  const hasGroups = Boolean(query.groups && query.groups.length > 0);
  if (!query.lookup && !query.conditions.length && !hasGroups) params.delete(PARAM);
  else params.set(PARAM, JSON.stringify(query));
}

export function queryFields(schema: DataSchema): DataAttribute[] {
  const attributes = schema.attributes.filter((item) => conditionOps(item).length > 0);
  if (!schema.row_id?.operators?.length) return attributes;
  return [{ name: "row_id", type: "integer", operators: schema.row_id.operators }, ...attributes];
}

export function conditionOps(field: DataAttribute): string[] {
  return availableFilterOperators(field.operators);
}

export function lookupOp(schema: DataSchema, field: DataAttribute): "eq" | "contains" | null {
  if (field.name !== schema.business_key && field.operators?.includes("contains"))
    return "contains";
  return field.operators?.includes("eq") ? "eq" : null;
}

export function lookupFields(schema: DataSchema, fields: DataAttribute[]): DataAttribute[] {
  const keys = [schema.business_key, "row_id"];
  const locators = keys.flatMap((name) =>
    fields.filter((field) => field.name === name && field.operators?.includes("eq")),
  );
  return [...locators, ...fields.filter((f) => !keys.includes(f.name) && lookupOp(schema, f))];
}

export function inputTypeOf(field: DataAttribute): string {
  if (field.type === "reference")
    return field.operators?.includes("contains") ? "string" : "integer";
  return field.type;
}

const BIGINT_MIN = BigInt("-9223372036854775808");
const BIGINT_MAX = BigInt("9223372036854775807");
const INVALID = Symbol("invalid-filter-value");
const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

function scalarValue(field: DataAttribute, raw: string, op?: string): unknown {
  const domain = op ? getFilterOperatorMeta(op).valueDomain : "field";
  if (domain === "string") {
    if (raw.includes("\u0000")) return INVALID;
    if (op === "ieq") return raw;
    return raw.length ? raw : INVALID;
  }
  if (domain === "json") {
    if (!raw.length || raw.includes("\u0000")) return INVALID;
    try {
      const parsed = parseEntityDataJson(raw);
      return parsed === undefined ? INVALID : parsed;
    } catch {
      return INVALID;
    }
  }
  if (!raw.length || raw.includes("\u0000")) return INVALID;
  const clean = raw.trim();
  switch (inputTypeOf(field)) {
    case "integer": {
      if (!/^[+-]?\d+$/.test(clean)) return INVALID;
      const n = BigInt(clean);
      const minimum = field.name === "row_id" ? BigInt(1) : BIGINT_MIN;
      if (n < minimum || n > BIGINT_MAX) return INVALID;
      const number = Number(n);
      return Number.isSafeInteger(number) ? number : n;
    }
    case "number":
      return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(clean) &&
        Number.isFinite(Number(clean))
        ? Number(clean)
        : INVALID;
    case "decimal":
      return DECIMAL.test(clean) ? clean : INVALID;
    case "boolean":
      return raw === "true" ? true : raw === "false" ? false : INVALID;
    case "dictionary":
      return field.codes?.some((code) => code.code === raw) ? raw : INVALID;
    case "date": {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return INVALID;
      const ms = Date.parse(raw);
      return Number.isFinite(ms) && new Date(ms).toISOString().startsWith(raw + "T")
        ? raw
        : INVALID;
    }
    case "timestamp":
      return Instant.epochMsOf(raw) !== null ? raw : INVALID;
    case "time":
      return /^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?$/.test(raw) ? raw : INVALID;
    case "json":
      try {
        return parseEntityDataJson(raw) ?? INVALID;
      } catch {
        return INVALID;
      }
    default:
      return raw;
  }
}

function group(terms: DataFilter[], mode: "all" | "any"): DataFilter {
  return terms.length === 1 ? terms[0] : mode === "all" ? { all: terms } : { any: terms };
}

type CompiledQuery = { ok: true; filters?: DataFilter } | { ok: false; error: string };

function compileConditionList(
  conditions: readonly QueryCondition[],
  fields: readonly DataAttribute[],
  counters: { leaves: number; inValues: number },
): { ok: true; terms: DataFilter[] } | { ok: false; error: string } {
  const terms: DataFilter[] = [];
  for (const { field: name, op, values, negate } of conditions) {
    const field = fields.find((item) => item.name === name);
    if (!field || !conditionOps(field).includes(op)) return { ok: false, error: ERROR + "field" };
    const meta = getFilterOperatorMeta(op);
    if (meta.arity === "none") {
      if (values.length !== 0) return { ok: false, error: ERROR + "value" };
      const leaf: DataFilter = { field: name, op };
      terms.push(negate ? { not: leaf } : leaf);
      counters.leaves += 1;
      continue;
    }
    if (meta.arity === "range") {
      if (values.length !== 2) return { ok: false, error: ERROR + "value" };
      const encoded = values.map((v) => scalarValue(field, v, op));
      if (encoded.includes(INVALID)) return { ok: false, error: ERROR + "value" };
      const leaf: DataFilter = { field: name, op, value: encoded };
      terms.push(negate ? { not: leaf } : leaf);
      counters.leaves += 1;
      continue;
    }
    if (meta.arity === "array") {
      if (!values.length) return { ok: false, error: ERROR + "value" };
      const encoded = values.map((v) => scalarValue(field, v, op));
      if (encoded.includes(INVALID)) return { ok: false, error: ERROR + "value" };
      const leaf: DataFilter = { field: name, op, value: encoded };
      terms.push(negate ? { not: leaf } : leaf);
      counters.inValues += encoded.length;
      counters.leaves += 1;
      continue;
    }
    if (values.length !== 1) return { ok: false, error: ERROR + "value" };
    const encoded = scalarValue(field, values[0], op);
    if (encoded === INVALID) return { ok: false, error: ERROR + "value" };
    const leaf: DataFilter = { field: name, op, value: encoded };
    terms.push(negate ? { not: leaf } : leaf);
    counters.leaves += 1;
  }
  return { ok: true, terms };
}

export function compileDataQuery(query: EntityDataQuery, schema: DataSchema): CompiledQuery {
  const fields = queryFields(schema);
  const counters = { leaves: 0, inValues: 0 };

  const rootRes = compileConditionList(query.conditions, fields, counters);
  if (!rootRes.ok) return rootRes;
  const rootParts: DataFilter[] = [...rootRes.terms];

  for (const sub of query.groups ?? []) {
    if (!sub.conditions.length) continue;
    const subRes = compileConditionList(sub.conditions, fields, counters);
    if (!subRes.ok) return subRes;
    rootParts.push(group(subRes.terms, sub.match));
  }

  const combined: DataFilter[] = [];
  if (query.lookup) {
    const { field: name, value } = query.lookup;
    const field = lookupFields(schema, fields).find((item) => item.name === name);
    if (!field) return { ok: false, error: ERROR + "field" };
    if (!value.trim()) return { ok: false, error: ERROR + "value" };
    const encoded = scalarValue(field, value);
    if (encoded === INVALID) return { ok: false, error: ERROR + "value" };
    const op = lookupOp(schema, field);
    if (!op) return { ok: false, error: ERROR + "field" };
    combined.push({ field: name, op, value: encoded });
    counters.leaves += 1;
  }
  if (
    counters.leaves > (schema.limits?.filter_leaves_max ?? 20) ||
    counters.inValues > (schema.limits?.filter_in_values_max ?? 1000)
  )
    return { ok: false, error: ERROR + "limit" };

  if (rootParts.length) {
    combined.push(group(rootParts, query.match));
  }
  if (!combined.length) return { ok: true };
  const filters = group(combined, "all");
  if (depthOf(filters) > (schema.limits?.filter_depth_max ?? 8))
    return { ok: false, error: ERROR + "limit" };
  return { ok: true, filters };
}

function depthOf(node: DataFilter): number {
  if ("field" in node) return 1;
  if ("not" in node) return 1 + depthOf(node.not);
  const children = "all" in node ? node.all : node.any;
  return 1 + Math.max(...children.map(depthOf));
}
