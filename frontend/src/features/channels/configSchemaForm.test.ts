import { describe, expect, it } from "vitest";

import {
  defaultConfig,
  fieldsFromSchema,
  omitUnsetIntegers,
  type SchemaObject,
} from "@/features/channels/configSchemaForm";

const READ: SchemaObject = {
  type: "object",
  additionalProperties: false,
  required: ["entity_id", "filters"],
  properties: {
    entity_id: { type: "string", "x-refraq-ref": "entity" },
    filters: {
      type: "array",
      items: {
        type: "object",
        required: ["attribute", "op", "value"],
        properties: {
          attribute: { type: "string", "x-refraq-ref": "entity_attribute" },
          op: { type: "string", enum: ["eq"] },
          value: { type: "string" },
        },
      },
    },
  },
} as SchemaObject;

const WRITE: SchemaObject = {
  type: "object",
  required: ["entity_id", "mode", "match_key", "mapping", "on_incompatible_head"],
  properties: {
    entity_id: { type: "string", "x-refraq-ref": "entity" },
    mode: { type: "string", enum: ["upsert", "create", "update", "delete"] },
    match_key: { type: ["string", "null"], "x-refraq-ref": "match_key" },
    mapping: {
      type: "array",
      items: {
        type: "object",
        required: ["attribute", "value"],
        properties: {
          attribute: { type: "string", "x-refraq-ref": "entity_attribute" },
          value: { type: "string" },
        },
      },
    },
    on_incompatible_head: { type: "string", enum: ["fail", "skip"] },
  },
};

describe("fieldsFromSchema", () => {
  it("maps entity refs, enums, and object lists", () => {
    const fields = fieldsFromSchema(READ);
    expect(fields.map((field) => field.kind)).toEqual(["entity", "objectList"]);
    const filters = fields[1];
    expect(filters?.kind).toBe("objectList");
    if (filters?.kind === "objectList") {
      expect(filters.fields.map((field) => field.kind)).toEqual([
        "attribute",
        "enum",
        "string",
      ]);
    }
  });

  it("maps an SQL source ref to the source picker", () => {
    const fields = fieldsFromSchema({
      type: "object",
      required: ["source"],
      properties: {
        source: {
          type: "object",
          description: "Entity database or a registered Source.",
          "x-refraq-ref": "sql_source",
        },
      },
    });
    expect(fields[0]).toMatchObject({
      kind: "sql_source",
      key: "source",
      required: true,
    });
    expect(defaultConfig({
      type: "object",
      properties: { source: { "x-refraq-ref": "sql_source" } },
    }).source).toBeNull();
  });

  it("maps a template field to a template editor", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        source: {
          type: "string",
          description: "Rows to write.",
          "x-refraq-template": { type: "array", items: { type: "object" } },
        },
      },
    });
    expect(fields[0]).toMatchObject({
      kind: "template",
      key: "source",
      description: "Rows to write.",
    });
  });

  it("treats a match key as an optional attribute", () => {
    const matchKey = fieldsFromSchema(WRITE).find((field) => field.key === "match_key");
    expect(matchKey).toEqual({
      kind: "attribute",
      key: "match_key",
      required: true,
      allowEmpty: true,
    });
  });
});

const TIMEOUT: SchemaObject = {
  type: "object",
  properties: {
    statement_timeout_sec: {
      type: "integer",
      minimum: 1,
      maximum: 3600,
      description: "Seconds before the statement is cancelled. Default 30.",
    },
    interval_seconds: {
      type: ["integer", "null"],
      minimum: 1,
    },
  },
};

describe("defaultConfig", () => {
  it("seeds write defaults the draft can store before references are chosen", () => {
    expect(defaultConfig(WRITE)).toEqual({
      entity_id: "",
      mode: "upsert",
      match_key: null,
      mapping: [],
      on_incompatible_head: "fail",
    });
  });

  it("omits an optional integer that cannot be null and keeps a nullable integer", () => {
    expect(defaultConfig(TIMEOUT)).toEqual({ interval_seconds: null });
    expect(fieldsFromSchema(TIMEOUT).find((field) => field.key === "statement_timeout_sec")).toMatchObject({
      kind: "integer",
      nullable: false,
      description: "Seconds before the statement is cancelled. Default 30.",
    });
  });
});

describe("omitUnsetIntegers", () => {
  it("drops a stored null on a non-nullable integer and keeps null where the type allows it", () => {
    expect(
      omitUnsetIntegers(
        { statement_timeout_sec: null, interval_seconds: null, sql: "select 1" },
        TIMEOUT,
      ),
    ).toEqual({ interval_seconds: null, sql: "select 1" });
  });
});
