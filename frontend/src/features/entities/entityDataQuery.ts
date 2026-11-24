import type { DataAttribute, DataSchema } from "./accessTypes";
import { parseEntityDataJson } from "./entityDataJson";
import { Instant } from "@/lib/instant";

export type QueryCondition = { field: string; op: string; values: string[] };
export type EntityDataQuery = {
  lookup: { field: string; value: string } | null;
  match: "all" | "any";
  conditions: QueryCondition[];
};

export const EMPTY_DATA_QUERY: EntityDataQuery = { lookup: null, match: "all", conditions: [] };

export type DataFilter =
  { field: string; op: string; value?: unknown } | { all: DataFilter[] } | { any: DataFilter[] };

const PARAM = "dataQuery";
const ERROR = "entities.data.query.error.";
const KNOWN_OPS = ["contains", "eq", "ne", "in", "gt", "gte", "lt", "lte", "is_null"];

function hasKeys(value: unknown, keys: string[]): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  return (
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
  );
}

function isCondition(value: unknown): value is QueryCondition {
  return (
    hasKeys(value, ["field", "op", "values"]) &&
    typeof value.field === "string" &&
    typeof value.op === "string" &&
    Array.isArray(value.values) &&
    value.values.every((item) => typeof item === "string")
  );
}

/** A malformed saved search must never turn into an unfiltered request. */
export function readDataQuery(params: Pick<URLSearchParams, "getAll">): EntityDataQuery | null {
  const encoded = params.getAll(PARAM);
  if (encoded.length === 0) return EMPTY_DATA_QUERY;
  if (encoded.length !== 1) return null;
  try {
    const parsed: unknown = JSON.parse(encoded[0]);
    if (!hasKeys(parsed, ["lookup", "match", "conditions"])) return null;
    const { lookup, match, conditions } = parsed;
    if (
      lookup !== null &&
      !(
        hasKeys(lookup, ["field", "value"]) &&
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
    return { lookup: lookup as EntityDataQuery["lookup"], match, conditions };
  } catch {
    return null;
  }
}

export function writeDataQuery(params: URLSearchParams, query: EntityDataQuery): void {
  if (!query.lookup && !query.conditions.length) params.delete(PARAM);
  else params.set(PARAM, JSON.stringify(query));
}

export function queryFields(schema: DataSchema): DataAttribute[] {
  const attributes = schema.attributes.filter((item) => conditionOps(item).length > 0);
  if (!schema.row_id?.operators?.length) return attributes;
  return [{ name: "row_id", type: "integer", operators: schema.row_id.operators }, ...attributes];
}

export function conditionOps(field: DataAttribute): string[] {
  const ops = KNOWN_OPS.filter((op) => field.operators?.includes(op));
  if (ops.includes("gte") && ops.includes("lte")) ops.splice(1, 0, "between");
  return ops;
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

function scalarValue(field: DataAttribute, raw: string): unknown {
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

function group(terms: DataFilter[], mode: EntityDataQuery["match"]): DataFilter {
  return terms.length === 1 ? terms[0] : mode === "all" ? { all: terms } : { any: terms };
}

type CompiledQuery = { ok: true; filters?: DataFilter } | { ok: false; error: string };

export function compileDataQuery(query: EntityDataQuery, schema: DataSchema): CompiledQuery {
  const fields = queryFields(schema);
  const terms: DataFilter[] = [];
  let leaves = 0;
  let inValues = 0;

  for (const { field: name, op, values } of query.conditions) {
    const field = fields.find((item) => item.name === name);
    if (!field || !conditionOps(field).includes(op)) return { ok: false, error: ERROR + "field" };
    const expected = op === "is_null" ? 0 : op === "between" ? 2 : 1;
    if (op === "in" ? !values.length : values.length !== expected)
      return { ok: false, error: ERROR + "value" };
    const encoded = values.map((value) => scalarValue(field, value));
    if (encoded.includes(INVALID)) return { ok: false, error: ERROR + "value" };
    if (op === "between") {
      terms.push({
        all: [
          { field: name, op: "gte", value: encoded[0] },
          { field: name, op: "lte", value: encoded[1] },
        ],
      });
      leaves += 2;
    } else {
      if (op === "is_null") terms.push({ field: name, op });
      else terms.push({ field: name, op, value: op === "in" ? encoded : encoded[0] });
      if (op === "in") inValues += encoded.length;
      leaves += 1;
    }
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
    leaves += 1;
  }
  if (
    leaves > (schema.limits?.filter_leaves_max ?? 20) ||
    inValues > (schema.limits?.filter_in_values_max ?? 1000)
  )
    return { ok: false, error: ERROR + "limit" };

  if (terms.length) combined.push(group(terms, query.match));
  if (!combined.length) return { ok: true };
  const filters = group(combined, "all");
  if (depthOf(filters) > (schema.limits?.filter_depth_max ?? 8))
    return { ok: false, error: ERROR + "limit" };
  return { ok: true, filters };
}

function depthOf(node: DataFilter): number {
  if ("field" in node) return 1;
  const children = "all" in node ? node.all : node.any;
  return 1 + Math.max(...children.map(depthOf));
}
