export type McpArgumentIssue =
  | { kind: "empty" }
  | { kind: "json"; reason: string }
  | { kind: "type"; path: string; expected: string }
  | { kind: "enum"; path: string; values: string }
  | { kind: "required"; path: string }
  | { kind: "additional"; path: string }
  | { kind: "minimum"; path: string; limit: number }
  | { kind: "maximum"; path: string; limit: number }
  | { kind: "minLength"; path: string; limit: number }
  | { kind: "maxLength"; path: string; limit: number }
  | { kind: "minItems"; path: string; limit: number }
  | { kind: "maxItems"; path: string; limit: number }
  | { kind: "pattern"; path: string; pattern: string };

export type McpArgumentCheck =
  | { ok: true; value: unknown }
  | { ok: false; issue: McpArgumentIssue };

const JSON_TYPES = ["object", "array", "string", "number", "integer", "boolean", "null"] as const;

type JsonType = (typeof JSON_TYPES)[number];

const JSON_TYPE_SET = new Set<string>(JSON_TYPES);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonType(value: string): value is JsonType {
  return JSON_TYPE_SET.has(value);
}

function matchesType(value: unknown, type: JsonType): boolean {
  switch (type) {
    case "object":
      return isRecord(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
  }
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function checkSchema(value: unknown, schema: unknown, path: string): McpArgumentIssue | null {
  if (!isRecord(schema)) return null;

  if (Array.isArray(schema.enum) && !schema.enum.some((item) => sameJson(item, value))) {
    return { kind: "enum", path, values: JSON.stringify(schema.enum) };
  }

  if ("type" in schema) {
    const listed = Array.isArray(schema.type) ? schema.type : [schema.type];
    const declared = listed.filter((item): item is string => typeof item === "string");
    const known = declared.filter(isJsonType);
    if (declared.length > 0 && known.length === declared.length && !known.some((item) => matchesType(value, item))) {
      return { kind: "type", path, expected: known.join(" or ") };
    }
  }

  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      return { kind: "minimum", path, limit: schema.minimum };
    }
    if (typeof schema.maximum === "number" && value > schema.maximum) {
      return { kind: "maximum", path, limit: schema.maximum };
    }
  }

  if (typeof value === "string") {
    if (typeof schema.minLength === "number" && value.length < schema.minLength) {
      return { kind: "minLength", path, limit: schema.minLength };
    }
    if (typeof schema.maxLength === "number" && value.length > schema.maxLength) {
      return { kind: "maxLength", path, limit: schema.maxLength };
    }
    if (typeof schema.pattern === "string") {
      try {
        if (!new RegExp(schema.pattern).test(value)) {
          return { kind: "pattern", path, pattern: schema.pattern };
        }
      } catch {
        // An unusable pattern is not a recognized constraint.
      }
    }
  }

  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) {
      return { kind: "minItems", path, limit: schema.minItems };
    }
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) {
      return { kind: "maxItems", path, limit: schema.maxItems };
    }
    if (isRecord(schema.items)) {
      for (let index = 0; index < value.length; index += 1) {
        const issue = checkSchema(value[index], schema.items, `${path}.${index}`);
        if (issue) return issue;
      }
    }
  }

  if (isRecord(value)) {
    const properties = isRecord(schema.properties) ? schema.properties : null;
    if (Array.isArray(schema.required)) {
      for (const key of schema.required) {
        if (typeof key !== "string") continue;
        if (!Object.prototype.hasOwnProperty.call(value, key)) {
          return { kind: "required", path: `${path}.${key}` };
        }
      }
    }
    if (properties) {
      for (const key of Object.keys(properties)) {
        if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
        const issue = checkSchema(value[key], properties[key], `${path}.${key}`);
        if (issue) return issue;
      }
    }
    if ("additionalProperties" in schema) {
      const known = new Set(properties ? Object.keys(properties) : []);
      for (const key of Object.keys(value)) {
        if (known.has(key)) continue;
        if (schema.additionalProperties === false) {
          return { kind: "additional", path: `${path}.${key}` };
        }
        if (isRecord(schema.additionalProperties)) {
          const issue = checkSchema(value[key], schema.additionalProperties, `${path}.${key}`);
          if (issue) return issue;
        }
      }
    }
  }

  return null;
}

/** Local JSON and applicable inputSchema checks. Empty text is not `{}`. */
export function checkArguments(text: string, schema: unknown): McpArgumentCheck {
  if (text.trim() === "") return { ok: false, issue: { kind: "empty" } };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    const reason = error instanceof Error ? error.message : "invalid JSON";
    return { ok: false, issue: { kind: "json", reason } };
  }
  if (schema === null || schema === undefined) return { ok: true, value };
  const issue = checkSchema(value, schema, "arguments");
  if (issue) return { ok: false, issue };
  return { ok: true, value };
}
