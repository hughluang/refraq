export type SchemaObject = {
  type?: string | string[];
  properties?: Record<string, SchemaObject>;
  required?: string[];
  additionalProperties?: boolean;
  items?: SchemaObject;
  enum?: string[];
  const?: string;
  default?: string;
  description?: string;
  title?: string;
  minimum?: number;
  maximum?: number;
  contentMediaType?: string;
  "x-refraq-dataset-reference"?: boolean;
  allOf?: { if?: SchemaObject; then?: SchemaObject }[];
  "x-refraq-ref"?: string;
  "x-refraq-template"?: SchemaObject | { from: "entity_attribute" };
};

/**
 * `equals`: show the field only while a sibling holds one of `values`.
 * `nullWhile`: hide the field while an `if` forces its value to null.
 * `present` means that `if` requires the sibling, so a missing sibling does not match.
 */
export type FieldWhen =
  | { kind: "equals"; key: string; values: readonly string[] }
  | { kind: "nullWhile"; key: string; values: readonly string[]; present: boolean };

export type FieldSpec = (
  | { kind: "string"; key: string; required: boolean; nullable: boolean }
  | { kind: "enum"; key: string; required: boolean; options: string[]; fallback: string }
  | { kind: "entity"; key: string; required: boolean; description: string }
  | { kind: "attribute"; key: string; required: boolean; allowEmpty: boolean }
  | { kind: "objectList"; key: string; required: boolean; description: string; fields: FieldSpec[] }
  | { kind: "stringList"; key: string; required: boolean; description: string }
  | {
      kind: "templateList";
      key: string;
      required: boolean;
      description: string;
      valueSchema: SchemaObject | { from: "entity_attribute" };
      itemDescription: string;
    }
  | { kind: "json"; key: string; required: boolean }
  | { kind: "sql_source"; key: string; required: boolean; description: string }
  | { kind: "source"; key: string; required: boolean; description: string }
  | { kind: "webhook"; key: string; required: boolean; description: string }
  | { kind: "email_account"; key: string; required: boolean; description: string }
  | { kind: "http_account"; key: string; required: boolean; description: string }
  | { kind: "python"; key: string; required: boolean; description: string }
  | {
      kind: "integer";
      key: string;
      required: boolean;
      nullable: boolean;
      description: string;
      minimum?: number;
      maximum?: number;
    }
  | {
      kind: "template";
      key: string;
      required: boolean;
      valueSchema: SchemaObject | { from: "entity_attribute" };
      description: string;
    }
) & { when?: FieldWhen };

export function fieldsFromSchema(schema: SchemaObject): FieldSpec[] {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const gates = visibilityGates(schema);
  return Object.entries(properties).map(([key, property]) => {
    const field = fieldFor(key, property, required.has(key));
    const when = gates.get(key);
    return when ? { ...field, when } : field;
  });
}

export function fieldVisible(
  field: { when?: FieldWhen },
  data: Record<string, unknown>,
): boolean {
  const when = field.when;
  if (!when) return true;
  if (when.kind === "nullWhile") return !nullWhileMatches(when, data);
  const current = data[when.key];
  const text = typeof current === "string" ? current : "";
  return when.values.includes(text);
}

/** Write null for a property whose schema branch forces null. Absent stays absent. */
export function nullForcedProperties(
  config: Record<string, unknown>,
  fields: readonly { key: string; when?: FieldWhen }[],
): Record<string, unknown> {
  let next = config;
  for (const field of fields) {
    const when = field.when;
    if (when?.kind !== "nullWhile" || !nullWhileMatches(when, next)) continue;
    if (!Object.prototype.hasOwnProperty.call(next, field.key) || next[field.key] === null) {
      continue;
    }
    if (next === config) next = { ...config };
    next[field.key] = null;
  }
  return next;
}

export function defaultConfig(schema: SchemaObject): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of fieldsFromSchema(schema)) {
    if (field.kind === "integer" && !field.nullable) continue;
    config[field.key] = defaultValue(field);
  }
  return config;
}

export function omitUnsetIntegers(
  config: Record<string, unknown>,
  schema: SchemaObject,
): Record<string, unknown> {
  const fields = fieldsFromSchema(schema);
  const next = { ...nullForcedProperties(config, fields) };
  for (const field of fields) {
    if (field.kind === "integer" && !field.nullable && next[field.key] === null) {
      delete next[field.key];
    }
  }
  return next;
}

function fieldFor(key: string, schema: SchemaObject, required: boolean): FieldSpec {
  if (schema["x-refraq-ref"] === "sql_source") {
    return { kind: "sql_source", key, required, description: schema.description ?? "" };
  }
  const template = schema["x-refraq-template"];
  if (template) {
    return {
      kind: "template",
      key,
      required,
      valueSchema: template,
      description: schema.description ?? "",
    };
  }
  const ref = schema["x-refraq-ref"];
  if (ref === "json") return { kind: "json", key, required };
  if (ref === "entity") {
    return { kind: "entity", key, required, description: schema.description ?? "" };
  }
  if (ref === "source") {
    return { kind: "source", key, required, description: schema.description ?? "" };
  }
  if (ref === "webhook") {
    return { kind: "webhook", key, required, description: schema.description ?? "" };
  }
  if (ref === "email_account") {
    return { kind: "email_account", key, required, description: schema.description ?? "" };
  }
  if (ref === "http_account") {
    return { kind: "http_account", key, required, description: schema.description ?? "" };
  }
  if (ref === "entity_attribute" || ref === "match_key") {
    return { kind: "attribute", key, required, allowEmpty: ref === "match_key" };
  }
  if (schema.enum && schema.enum.length > 0) {
    const fallback =
      typeof schema.default === "string" && schema.enum.includes(schema.default)
        ? schema.default
        : (schema.enum[0] ?? "");
    return { kind: "enum", key, required, options: schema.enum, fallback };
  }
  const typeName = schemaType(schema);
  if (typeName === "integer" || typeName === "number") {
    return {
      kind: "integer",
      key,
      required,
      nullable: allowsNull(schema),
      description: schema.description ?? "",
      minimum: typeof schema.minimum === "number" ? schema.minimum : undefined,
      maximum: typeof schema.maximum === "number" ? schema.maximum : undefined,
    };
  }
  if (typeName === "array") {
    return arrayField(key, schema, required);
  }
  if (schema.contentMediaType === "text/x-python" && (typeName === "string" || typeName === null)) {
    return { kind: "python", key, required, description: schema.description ?? "" };
  }
  return { kind: "string", key, required, nullable: allowsNull(schema) };
}

function arrayField(key: string, schema: SchemaObject, required: boolean): FieldSpec {
  const item = schema.items;
  const template = item?.["x-refraq-template"];
  if (item && template) {
    return {
      kind: "templateList",
      key,
      required,
      description: schema.description ?? "",
      valueSchema: template,
      itemDescription: item.description ?? "",
    };
  }
  if (item && (item.type === "object" || item.properties)) {
    return {
      kind: "objectList",
      key,
      required,
      description: schema.description ?? "",
      fields: fieldsFromSchema(item),
    };
  }
  if (item && schemaType(item) === "string") {
    return { kind: "stringList", key, required, description: schema.description ?? "" };
  }
  return {
    kind: "objectList",
    key,
    required,
    description: schema.description ?? "",
    fields: [],
  };
}

/**
 * A property that an `if`/`then` adds to `required` is shown only while that `if` matches.
 * A property that the same `then` forces to null is hidden while that `if` matches.
 */
function visibilityGates(schema: SchemaObject): Map<string, FieldWhen> {
  const gates = new Map<string, FieldWhen>();
  const baseRequired = new Set(schema.required ?? []);
  for (const clause of schema.allOf ?? []) {
    const test = clause.if;
    const thenRequired = clause.then?.required ?? [];
    if (!test?.properties) continue;
    const entries = Object.entries(test.properties);
    if (entries.length !== 1) continue;
    const [control, rule] = entries[0] ?? [];
    if (!control || !rule) continue;
    const values = ruleValues(rule);
    if (!values) continue;
    for (const prop of thenRequired) {
      if (prop === control || baseRequired.has(prop) || gates.has(prop)) continue;
      gates.set(prop, { kind: "equals", key: control, values });
    }
    const present = (test.required ?? []).includes(control);
    for (const [prop, forced] of Object.entries(clause.then?.properties ?? {})) {
      if (forced.type !== "null") continue;
      if (prop === control || baseRequired.has(prop) || gates.has(prop)) continue;
      gates.set(prop, { kind: "nullWhile", key: control, values, present });
    }
  }
  return gates;
}

function nullWhileMatches(
  when: Extract<FieldWhen, { kind: "nullWhile" }>,
  data: Record<string, unknown>,
): boolean {
  const current = data[when.key];
  if (typeof current !== "string") return !when.present;
  return when.values.includes(current);
}

function ruleValues(rule: SchemaObject): string[] | null {
  if (rule.enum && rule.enum.length > 0) return [...rule.enum];
  if (typeof rule.const === "string") return [rule.const];
  return null;
}

function schemaType(schema: SchemaObject): string | null {
  if (typeof schema.type === "string") return schema.type;
  if (Array.isArray(schema.type)) {
    return schema.type.find((item) => item !== "null") ?? null;
  }
  return null;
}

function allowsNull(schema: SchemaObject): boolean {
  return Array.isArray(schema.type) && schema.type.includes("null");
}

export function emptyRow(fields: FieldSpec[]): Record<string, unknown> {
  const row: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.kind === "integer" && !field.nullable) continue;
    row[field.key] = defaultValue(field);
  }
  return row;
}

function defaultValue(field: FieldSpec): unknown {
  switch (field.kind) {
    case "enum":
      return field.fallback;
    case "entity":
      return "";
    case "string":
      return field.nullable ? null : "";
    case "attribute":
      return field.allowEmpty ? null : "";
    case "objectList":
    case "stringList":
    case "templateList":
      return [];
    case "json":
      return {};
    case "template":
      return "";
    case "sql_source":
      return null;
    case "source":
    case "webhook":
    case "email_account":
      return "";
    case "http_account":
      return null;
    case "python":
      return "";
    case "integer":
      return null;
  }
}
