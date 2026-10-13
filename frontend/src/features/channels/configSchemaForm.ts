export type SchemaObject = {
  type?: string | string[];
  properties?: Record<string, SchemaObject>;
  required?: string[];
  items?: SchemaObject;
  enum?: string[];
  description?: string;
  minimum?: number;
  maximum?: number;
  "x-refraq-ref"?: string;
  "x-refraq-template"?: SchemaObject | { from: "entity_attribute" };
};

export type FieldSpec =
  | { kind: "string"; key: string; required: boolean }
  | { kind: "enum"; key: string; required: boolean; options: string[] }
  | { kind: "entity"; key: string; required: boolean }
  | { kind: "attribute"; key: string; required: boolean; allowEmpty: boolean }
  | { kind: "objectList"; key: string; required: boolean; description: string; fields: FieldSpec[] }
  | { kind: "json"; key: string; required: boolean }
  | { kind: "sql_source"; key: string; required: boolean; description: string }
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
    };

export function fieldsFromSchema(schema: SchemaObject): FieldSpec[] {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  return Object.entries(properties).map(([key, property]) =>
    fieldFor(key, property, required.has(key)),
  );
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
  const next = { ...config };
  for (const field of fieldsFromSchema(schema)) {
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
  if (ref === "entity") return { kind: "entity", key, required };
  if (ref === "entity_attribute" || ref === "match_key") {
    return { kind: "attribute", key, required, allowEmpty: ref === "match_key" };
  }
  if (schema.enum && schema.enum.length > 0) {
    return { kind: "enum", key, required, options: schema.enum };
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
    const item = schema.items;
    const fields =
      item && (item.type === "object" || item.properties)
        ? fieldsFromSchema(item)
        : [];
    return { kind: "objectList", key, required, description: schema.description ?? "", fields };
  }
  return { kind: "string", key, required };
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
      return field.options[0] ?? "";
    case "entity":
    case "string":
      return "";
    case "attribute":
      return field.allowEmpty ? null : "";
    case "objectList":
      return [];
    case "json":
      return {};
    case "template":
      return "";
    case "sql_source":
      return null;
    case "integer":
      return null;
  }
}
