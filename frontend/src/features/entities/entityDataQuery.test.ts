import { describe, expect, it } from "vitest";

import type { DataSchema } from "./accessTypes";
import {
  compileDataQuery,
  EMPTY_DATA_QUERY,
  lookupFields,
  queryFields,
  readDataQuery,
  writeDataQuery,
  type EntityDataQuery,
  type QueryCondition,
} from "./entityDataQuery";

const schema: DataSchema = {
  entity: { table_name: "parts", name: "Parts", writable: false },
  withheld_field: null,
  business_key: "sku",
  row_id: { type: "integer", operators: ["eq", "in", "gte", "lte"] },
  limits: {
    page_limit_default: 50,
    page_limit_max: 200,
    filter_depth_max: 8,
    filter_leaves_max: 20,
    filter_in_values_max: 1000,
  },
  attributes: [
    { name: "sku", type: "string", operators: ["eq", "contains", "in"] },
    { name: "notes", type: "text", operators: ["eq", "contains", "is_null"] },
    { name: "on_sale", type: "boolean", operators: ["eq", "ne"] },
    { name: "due", type: "date", operators: ["eq", "gte", "lte", "between"] },
    { name: "price", type: "decimal", operators: ["eq"] },
    { name: "replacement", type: "reference", operators: ["eq", "gt", "lt"] },
    {
      name: "state",
      type: "dictionary",
      operators: ["in", "eq"],
      codes: [
        { code: "open", label: "Open", writable: true },
        { code: "old", label: null, writable: false },
      ],
    },
  ],
};

function filters(...conditions: QueryCondition[]) {
  return compileDataQuery({ ...EMPTY_DATA_QUERY, conditions }, schema);
}

describe("entity data viewer queries", () => {
  it("offers only visible exact locators and supported text search", () => {
    expect(lookupFields(schema, queryFields(schema)).map((f) => f.name)).toEqual([
      "sku",
      "row_id",
      "notes",
      "on_sale",
      "due",
      "price",
      "replacement",
      "state",
    ]);
    expect(
      compileDataQuery({ ...EMPTY_DATA_QUERY, lookup: { field: "row_id", value: "42" } }, schema),
    ).toEqual({ ok: true, filters: { field: "row_id", op: "eq", value: 42 } });
    expect(
      compileDataQuery({ ...EMPTY_DATA_QUERY, lookup: { field: "notes", value: "100%" } }, schema),
    ).toEqual({ ok: true, filters: { field: "notes", op: "contains", value: "100%" } });
  });

  it.each([
    ["due", "2026-11-24", "2026-11-24"],
    ["on_sale", "false", false],
    ["state", "old", "old"],
    ["replacement", "00023", 23],
    ["price", "42.00", "42.00"],
  ])("quick lookup encodes the selected %s field", (field, text, value) => {
    expect(
      compileDataQuery(
        { ...EMPTY_DATA_QUERY, lookup: { field: String(field), value: String(text) } },
        schema,
      ),
    ).toEqual({ ok: true, filters: { field, op: "eq", value } });
  });

  it("requires the lookup and groups alternatives separately, preserving exact strings and inactive codes", () => {
    const query: EntityDataQuery = {
      lookup: { field: "sku", value: "00042" },
      match: "any",
      conditions: [
        { field: "state", op: "in", values: ["old", "open"] },
        { field: "due", op: "between", values: ["2026-01-01", "2026-02-28"] },
        { field: "on_sale", op: "eq", values: ["false"] },
      ],
    };
    expect(compileDataQuery(query, schema)).toEqual({
      ok: true,
      filters: {
        all: [
          { field: "sku", op: "eq", value: "00042" },
          {
            any: [
              { field: "state", op: "in", value: ["old", "open"] },
              { field: "due", op: "between", value: ["2026-01-01", "2026-02-28"] },
              { field: "on_sale", op: "eq", value: false },
            ],
          },
        ],
      },
    });
  });

  it("sends precise decimals, reference numbers and value-free null checks", () => {
    expect(
      filters(
        { field: "price", op: "eq", values: ["9007199254740993.50"] },
        { field: "replacement", op: "eq", values: ["42"] },
        { field: "notes", op: "is_null", values: [] },
      ),
    ).toEqual({
      ok: true,
      filters: {
        all: [
          { field: "price", op: "eq", value: "9007199254740993.50" },
          { field: "replacement", op: "eq", value: 42 },
          { field: "notes", op: "is_null" },
        ],
      },
    });
  });

  it.each([
    ["row_id", "9007199254740993"],
    ["row_id", "9223372036854775807"],
    ["replacement", "-9223372036854775808"],
  ])("preserves full-width integers in %s lookups and filters", (field, text) => {
    const expected = { ok: true, filters: { field, op: "eq", value: BigInt(text) } };
    expect(filters({ field, op: "eq", values: [text] })).toEqual(expected);
    expect(
      compileDataQuery({ ...EMPTY_DATA_QUERY, lookup: { field, value: text } }, schema),
    ).toEqual(expected);
  });

  it("preserves integer literals nested in a JSON filter", () => {
    const payload = '{"nested":[1,9007199254740993]}';
    const jsonSchema = {
      ...schema,
      attributes: [{ name: "payload", type: "json", operators: ["eq"] }],
    };
    expect(
      compileDataQuery(
        { ...EMPTY_DATA_QUERY, lookup: { field: "payload", value: payload } },
        jsonSchema,
      ),
    ).toEqual({
      ok: true,
      filters: { field: "payload", op: "eq", value: { nested: [1, BigInt("9007199254740993")] } },
    });
  });

  it.each<QueryCondition>([
    { field: "hidden", op: "eq", values: ["x"] },
    { field: "sku", op: "gte", values: ["x"] },
    { field: "state", op: "eq", values: ["missing-code"] },
    { field: "due", op: "between", values: ["2026-02-30", "2026-03-04"] },
    { field: "notes", op: "is_null", values: ["unexpected"] },
    { field: "row_id", op: "eq", values: ["9223372036854775808"] },
    { field: "replacement", op: "eq", values: ["-9223372036854775809"] },
    { field: "row_id", op: "eq", values: ["-1"] },
    { field: "row_id", op: "eq", values: ["0"] },
  ])("rejects an unsupported or invalid condition %o", (condition) => {
    expect(filters(condition).ok).toBe(false);
  });

  it("respects advertised leaf, total membership value, and group depth limits", () => {
    const conditions = [
      { field: "due", op: "between", values: ["2026-01-01", "2026-01-31"], negate: true },
      { field: "state", op: "in", values: ["open", "old"] },
    ];
    const query = {
      lookup: { field: "row_id", value: "23" },
      match: "any" as const,
      conditions,
    };
    for (const limit of [
      { filter_leaves_max: 2 },
      { filter_depth_max: 3 },
      { filter_in_values_max: 1 },
    ]) {
      expect(
        compileDataQuery(query, { ...schema, limits: { ...schema.limits!, ...limit } }),
      ).toEqual({ ok: false, error: "entities.data.query.error.limit" });
    }
  });

  it("round-trips a link without touching the selected tab, including literal punctuation", () => {
    const params = new URLSearchParams("tab=data&dataPage=2");
    const query: EntityDataQuery = {
      ...EMPTY_DATA_QUERY,
      lookup: { field: "sku", value: "A+/#&B" },
    };
    writeDataQuery(params, query);
    expect(readDataQuery(new URLSearchParams(params.toString()))).toEqual(query);
    writeDataQuery(params, EMPTY_DATA_QUERY);
    expect([...params]).toEqual([
      ["tab", "data"],
      ["dataPage", "2"],
    ]);
    expect(readDataQuery(params)).toEqual(EMPTY_DATA_QUERY);
  });

  it("refuses duplicate keys, malformed JSON, unsupported shapes and stale schema links", () => {
    for (const value of [
      "",
      "{",
      "[1]",
      '{"lookup":null,"conditions":[],"match":"all","search":"vanished"}',
    ]) {
      expect(readDataQuery(new URLSearchParams({ dataQuery: value }))).toBeNull();
    }
    const params = new URLSearchParams();
    writeDataQuery(params, { ...EMPTY_DATA_QUERY, lookup: { field: "secret_name", value: "x" } });
    expect(compileDataQuery(readDataQuery(params)!, schema).ok).toBe(false);
    params.append("dataQuery", "{}");
    expect(readDataQuery(params)).toBeNull();
  });
});
