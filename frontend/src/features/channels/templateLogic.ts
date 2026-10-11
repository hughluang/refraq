import type { SchemaObject } from "@/features/channels/configSchemaForm";

export type TemplateValueSchema = SchemaObject | { from: "entity_attribute" };

export type UpstreamOutput = {
  ref: string;
  paths: readonly string[];
};

export type CompletionQuery =
  | { kind: "ref"; start: number; filter: string }
  | { kind: "path"; start: number; ref: string; filter: string };

export type TemplatePreview =
  | { state: "deferred" }
  | { state: "unknown" }
  | { state: "ok"; value: unknown }
  | { state: "error" };

export type TemplateRule = "text" | "json";

const RESOLVED_LIMIT = 80;

const IDENT = "[A-Za-z_][A-Za-z0-9_]*";

export function attributeValueSchema(attributeType: string): SchemaObject {
  const scalar: Record<string, string> = {
    string: "string",
    text: "string",
    user: "string",
    dictionary: "string",
    reference: "string",
    integer: "integer",
    number: "number",
    decimal: "number",
    boolean: "boolean",
    date: "string",
    timestamp: "string",
    time: "string",
  };
  if (attributeType === "json") {
    return { type: ["object", "array", "string", "number", "boolean", "null"] };
  }
  return { type: [scalar[attributeType] ?? "string", "null"] };
}

export function typeBadge(schema: TemplateValueSchema | null): string {
  if (schema == null) return "unknown";
  if ("from" in schema) return "attribute";
  const names = typeNames(schema);
  if (names.length === 0) return "unknown";
  if (schema.type === "array") return "list";
  return names.filter((name) => name !== "null").join(" | ") || "unknown";
}

export function hasCalculation(text: string): boolean {
  const source = text.trim();
  let index = 0;
  while (index < source.length) {
    if (source[index] === "\\") {
      let count = 0;
      while (source[index] === "\\") {
        count += 1;
        index += 1;
      }
      if (source.startsWith("{{", index)) {
        if (count % 2 === 0) return true;
        index += 2;
        continue;
      }
      continue;
    }
    if (source.startsWith("{{", index)) return true;
    index += 1;
  }
  return false;
}

export function templatePreview(text: string, schema: SchemaObject | null): TemplatePreview {
  if (schema == null) return { state: "unknown" };
  if (hasCalculation(text)) return { state: "deferred" };
  if (isStringTarget(schema)) return { state: "ok", value: text.trim() };
  try {
    const parsed: unknown = JSON.parse(text.trim());
    return valueMatches(parsed, schema) ? { state: "ok", value: parsed } : { state: "error" };
  } catch {
    return { state: "error" };
  }
}

export function templateRule(schema: SchemaObject | null): TemplateRule | null {
  if (schema == null || typeNames(schema).length === 0) return null;
  return isStringTarget(schema) ? "text" : "json";
}

export function resolvedText(value: unknown): string {
  const encoded = JSON.stringify(value);
  const text = typeof encoded === "string" ? encoded : "";
  if (text.length <= RESOLVED_LIMIT) return text;
  return `${text.slice(0, RESOLVED_LIMIT - 1)}…`;
}

export function completionQuery(text: string, cursor: number): CompletionQuery | null {
  const before = text.slice(0, cursor);
  const path = before.match(
    new RegExp(`self\\.(${IDENT})\\.output\\.?(${IDENT})?$`),
  );
  if (path?.[1]) {
    return {
      kind: "path",
      start: before.length - path[0].length,
      ref: path[1],
      filter: path[2] ?? "",
    };
  }
  const ref = before.match(new RegExp(`self\\.(${IDENT})?$`));
  if (!ref) return null;
  const filter = ref[1] ?? "";
  return { kind: "ref", start: before.length - ref[0].length, filter };
}

export function completionLabels(
  query: CompletionQuery,
  upstream: readonly UpstreamOutput[],
): string[] {
  if (query.kind === "ref") {
    return upstream
      .map((item) => item.ref)
      .filter((ref) => ref.startsWith(query.filter));
  }
  const node = upstream.find((item) => item.ref === query.ref);
  if (!node) return [];
  return node.paths.filter((path) => {
    const suffix = path === "output" ? "" : path.slice("output.".length);
    return suffix.startsWith(query.filter);
  });
}

export function outputPaths(schema: SchemaObject | null | undefined): string[] {
  if (schema?.type !== "object" || !schema.properties) return ["output"];
  return ["output", ...Object.keys(schema.properties).map((key) => `output.${key}`)];
}

export function applyCompletion(
  text: string,
  cursor: number,
  query: CompletionQuery,
  label: string,
): { next: string; cursor: number } {
  const inserted =
    query.kind === "ref"
      ? `self.${label}`
      : label === "output"
        ? `self.${query.ref}.output`
        : `self.${query.ref}.${label}`;
  const next = text.slice(0, query.start) + inserted + text.slice(cursor);
  return { next, cursor: query.start + inserted.length };
}

export function upstreamOutputs(
  nodeId: string,
  nodes: readonly { id: string; ref: string }[],
  edges: readonly { source: string; target: string }[],
  schemas: ReadonlyMap<string, SchemaObject | null>,
): UpstreamOutput[] {
  const incoming = new Map<string, string[]>();
  for (const edge of edges) {
    const list = incoming.get(edge.target) ?? [];
    list.push(edge.source);
    incoming.set(edge.target, list);
  }
  const seen = new Set<string>();
  const stack = [...(incoming.get(nodeId) ?? [])];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    stack.push(...(incoming.get(current) ?? []));
  }
  return nodes
    .filter((node) => seen.has(node.id) && node.ref)
    .map((node) => ({ ref: node.ref, paths: outputPaths(schemas.get(node.id)) }));
}

function typeNames(schema: SchemaObject): string[] {
  if (typeof schema.type === "string") return [schema.type];
  if (Array.isArray(schema.type)) return schema.type;
  return [];
}

function isStringTarget(schema: SchemaObject): boolean {
  const names = new Set(typeNames(schema));
  names.delete("null");
  return names.size === 1 && names.has("string");
}

function valueMatches(value: unknown, schema: SchemaObject): boolean {
  const names = typeNames(schema);
  if (names.length === 0) return false;
  return names.some((name) => typeMatches(value, name, schema));
}

function typeMatches(value: unknown, name: string, schema: SchemaObject): boolean {
  if (name === "null") return value === null;
  if (name === "string") return typeof value === "string";
  if (name === "boolean") return typeof value === "boolean";
  if (name === "integer") return typeof value === "number" && Number.isInteger(value);
  if (name === "number") return typeof value === "number";
  if (name === "array") {
    if (!Array.isArray(value)) return false;
    const items = schema.items;
    if (!items) return true;
    return value.every((item) => valueMatches(item, items));
  }
  if (name === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  return false;
}
