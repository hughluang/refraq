import { describe, expect, it } from "vitest";

import {
  defaultConfig,
  fieldVisible,
  fieldsFromSchema,
  nullForcedProperties,
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

  it("lets a template marker win over an unregistered sql ref", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        sql: {
          type: "string",
          description: "One statement.",
          "x-refraq-template": { type: "string" },
          "x-refraq-ref": "sql",
        },
      },
    });
    expect(fields[0]).toMatchObject({
      kind: "template",
      key: "sql",
      description: "One statement.",
    });
  });

  it("lets a template marker choose the control when an unregistered sql ref is also present", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        sql: {
          type: "string",
          description: "One statement.",
          "x-refraq-template": { type: "string" },
          "x-refraq-ref": "sql",
        },
      },
    });
    expect(fields[0]).toMatchObject({
      kind: "template",
      key: "sql",
      description: "One statement.",
    });
    expect(defaultConfig({
      type: "object",
      properties: {
        sql: {
          "x-refraq-template": { type: "string" },
          "x-refraq-ref": "sql",
        },
      },
    }).sql).toBe("");
  });

  it("keeps an object list description and drops child descriptions", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        mapping: {
          type: "array",
          description: "Attributes to write.",
          items: {
            type: "object",
            properties: {
              attribute: {
                type: "string",
                description: "Head attribute.",
                "x-refraq-ref": "entity_attribute",
              },
              key: { type: "string", description: "Source key." },
            },
          },
        },
      },
    });
    const mapping = fields[0];
    expect(mapping).toMatchObject({
      kind: "objectList",
      description: "Attributes to write.",
    });
    if (mapping?.kind === "objectList") {
      expect(mapping.fields.map((field) => ("description" in field ? field.description : null))).toEqual([
        null,
        null,
      ]);
    }
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

  it("keeps a dataset reference template from collapsing to an anonymous string", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        dataset: {
          type: "string",
          "x-refraq-template": {
            type: "object",
            "x-refraq-dataset-reference": true,
            required: ["dataset_id", "columns", "count"],
          },
        },
        source: {
          type: "string",
          "x-refraq-template": {
            type: ["array", "object"],
            "x-refraq-dataset-reference": true,
          },
        },
      },
    });
    expect(fields[0]).toMatchObject({ kind: "template", key: "dataset" });
    expect(fields[0]?.kind === "template" ? fields[0].valueSchema : null).toMatchObject({
      "x-refraq-dataset-reference": true,
    });
    expect(fields[1]).toMatchObject({ kind: "template" });
    expect(fields.map((field) => field.kind)).not.toContain("string");
  });

  it("maps a json ref to an object field", () => {
    const schema: SchemaObject = {
      type: "object",
      properties: {
        payload: { type: "object", "x-refraq-ref": "json" },
      },
    };
    expect(fieldsFromSchema(schema)[0]).toEqual({
      kind: "json",
      key: "payload",
      required: false,
    });
    expect(defaultConfig(schema).payload).toEqual({});
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

const FILTER: SchemaObject = {
  type: "object",
  required: ["items", "conditions"],
  properties: {
    items: {
      type: "string",
      "x-refraq-template": { type: "array" },
    },
    combinator: { type: "string", enum: ["all", "any"], default: "all" },
    conditions: {
      type: "array",
      items: {
        type: "object",
        required: ["key", "operator"],
        properties: {
          key: { type: "string" },
          operator: { type: "string", enum: ["eq", "is_null", "is_not_null"] },
          value: { type: "string", "x-refraq-template": { type: "string" } },
        },
        allOf: [
          {
            if: { properties: { operator: { enum: ["eq"] } }, required: ["operator"] },
            then: { required: ["key", "operator", "value"] },
          },
        ],
      },
    },
  },
};

const MERGE: SchemaObject = {
  type: "object",
  required: ["mode", "inputs"],
  properties: {
    mode: { type: "string", enum: ["append", "by_key", "by_position"] },
    inputs: {
      type: "array",
      items: {
        type: "string",
        description: "One list.",
        "x-refraq-template": { type: "array" },
      },
    },
    key: {
      type: ["string", "null"],
      description: "Field matched by by_key.",
    },
    join: {
      type: "string",
      enum: ["inner", "left", "full"],
      default: "inner",
      description: "inner, left, or full. Default inner. append ignores it.",
    },
  },
  allOf: [
    {
      if: { properties: { mode: { const: "by_key" } }, required: ["mode"] },
      then: { required: ["key"] },
    },
  ],
};

describe("reshape config schemas", () => {
  it("maps string lists, template lists, nullable strings, and enum defaults", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        keys: { type: "array", description: "Field names.", items: { type: "string" } },
        inputs: MERGE.properties?.inputs,
        key: MERGE.properties?.key,
        join: { type: "string", enum: ["inner", "left"], default: "left" },
      },
    });
    expect(fields.map((field) => field.kind)).toEqual([
      "stringList",
      "templateList",
      "string",
      "enum",
    ]);
    expect(fields[2]).toMatchObject({ kind: "string", nullable: true });
    expect(fields[3]).toMatchObject({ kind: "enum", fallback: "left" });
    expect(defaultConfig(MERGE)).toEqual({
      mode: "append",
      inputs: [],
      key: null,
      join: "inner",
    });
    expect(defaultConfig(FILTER).combinator).toBe("all");
  });

  it("shows a condition value only when the operator needs one and hides the merge key outside by_key", () => {
    const conditions = fieldsFromSchema(FILTER).find((field) => field.key === "conditions");
    expect(conditions?.kind).toBe("objectList");
    if (conditions?.kind !== "objectList") return;
    const value = conditions.fields.find((field) => field.key === "value");
    expect(fieldVisible(value ?? {}, { operator: "eq" })).toBe(true);
    expect(fieldVisible(value ?? {}, { operator: "is_null" })).toBe(false);
    expect(fieldVisible(value ?? {}, { operator: "is_not_null" })).toBe(false);

    const merge = fieldsFromSchema(MERGE);
    const key = merge.find((field) => field.key === "key") ?? {};
    const join = merge.find((field) => field.key === "join") ?? {};
    expect(fieldVisible(key, { mode: "append" })).toBe(false);
    expect(fieldVisible(join, { mode: "append" })).toBe(true);
    expect(fieldVisible(key, { mode: "by_key" })).toBe(true);
    expect(fieldVisible(join, { mode: "by_key" })).toBe(true);
    expect(fieldVisible(key, { mode: "by_position" })).toBe(false);
    expect(fieldVisible(join, { mode: "by_position" })).toBe(true);
  });

  it("hides a property the schema forces to null and keeps it when that if does not match", () => {
    const ttl = fieldsFromSchema(VARIABLE).find((field) => field.key === "ttl_sec") ?? {};
    expect(fieldVisible(ttl, { scope: "run" })).toBe(false);
    expect(fieldVisible(ttl, { scope: "site" })).toBe(true);
    expect(fieldVisible(ttl, { scope: "channel" })).toBe(true);
    expect(fieldVisible(ttl, {})).toBe(true);
  });
});

describe("code and source query config", () => {
  it("maps a source id and python source to their editors and omits the defaulted timeout", () => {
    const schema: SchemaObject = {
      type: "object",
      required: ["source_id", "code"],
      properties: {
        source_id: {
          type: "string",
          description: "Which Source",
          "x-refraq-ref": "source",
        },
        code: {
          type: "string",
          description: "Body of main",
          contentMediaType: "text/x-python",
        },
        timeout_sec: { type: "integer", minimum: 1, maximum: 300 },
      },
    };
    expect(fieldsFromSchema(schema).map((field) => [field.kind, field.key])).toEqual([
      ["source", "source_id"],
      ["python", "code"],
      ["integer", "timeout_sec"],
    ]);
    expect(fieldsFromSchema(schema)[0]).toMatchObject({
      kind: "source",
      description: "Which Source",
      required: true,
    });
    expect(fieldsFromSchema(schema)[1]).toMatchObject({
      kind: "python",
      description: "Body of main",
    });
    expect(defaultConfig(schema)).toEqual({ source_id: "", code: "" });
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

  it("writes null for a run expiry and leaves a site or omitted scope alone", () => {
    const fields = fieldsFromSchema(VARIABLE);
    expect(nullForcedProperties({ scope: "run", ttl_sec: 5 }, fields)).toEqual({
      scope: "run",
      ttl_sec: null,
    });
    expect(nullForcedProperties({ scope: "run" }, fields)).toEqual({ scope: "run" });
    expect(nullForcedProperties({ scope: "site", ttl_sec: 5 }, fields)).toEqual({
      scope: "site",
      ttl_sec: 5,
    });
    expect(nullForcedProperties({ ttl_sec: 5 }, fields)).toEqual({ ttl_sec: 5 });
    expect(omitUnsetIntegers({ scope: "run", ttl_sec: 5, name: "step" }, VARIABLE)).toEqual({
      scope: "run",
      ttl_sec: null,
      name: "step",
    });
  });
});

const VARIABLE: SchemaObject = {
  type: "object",
  required: ["operation", "name"],
  properties: {
    scope: { type: "string", enum: ["site", "channel", "run"], default: "site" },
    operation: { type: "string" },
    name: { type: "string" },
    ttl_sec: { type: ["integer", "null"], minimum: 1 },
  },
  allOf: [
    {
      if: { properties: { scope: { const: "run" } }, required: ["scope"] },
      then: { properties: { ttl_sec: { type: "null" } } },
    },
  ],
};
