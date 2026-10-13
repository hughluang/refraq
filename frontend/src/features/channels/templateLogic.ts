import type { SchemaObject } from "@/features/channels/configSchemaForm";
import { scanTemplate, templatePosition } from "@/features/channels/templateScan";

export type TemplateValueSchema = SchemaObject | { from: "entity_attribute" };

export type UpstreamOutput = {
  ref: string;
  name: string;
  paths: readonly string[];
};

type CompletionQuery =
  | { kind: "ref"; start: number; filter: string }
  | { kind: "path"; start: number; ref: string; filter: string };

export type TemplatePreview =
  | { state: "deferred" }
  | { state: "string" }
  | { state: "unknown" }
  | { state: "invalid" }
  | { state: "ok"; value: unknown }
  | { state: "error" };

export type TemplateCompletion = {
  from: number;
  options: string[];
};

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

export function templatePreview(text: string, schema: SchemaObject | null): TemplatePreview {
  const scanned = scanTemplate(text);
  if (!scanned.ok) return { state: "invalid" };
  if (schema == null) return { state: "unknown" };
  if (scanned.hasExpression) {
    if (scanned.wholeExpression || !isStringTarget(schema)) return { state: "deferred" };
    return { state: "string" };
  }
  if (isStringTarget(schema)) return { state: "ok", value: scanned.staticText };
  try {
    const parsed: unknown = JSON.parse(scanned.staticText);
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

function completionQuery(text: string, cursor: number): CompletionQuery | null {
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

function completionLabels(
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

export function templateCompletions(
  text: string,
  cursor: number,
  explicit: boolean,
  upstream: readonly UpstreamOutput[],
): TemplateCompletion | null {
  const position = templatePosition(text, cursor);
  if (position.kind === "outside" || position.kind === "string") return null;
  if (position.kind === "nodeKey") {
    const names = upstream
      .map((item) => item.name)
      .filter((name) => name !== "" && name.startsWith(position.filter));
    if (names.length === 0) return null;
    return {
      from: position.start,
      options: names.map((name) => `self.nodes[${JSON.stringify(name)}]`),
    };
  }
  const query = completionQuery(text, cursor);
  if (query) {
    const labels = completionLabels(query, upstream);
    if (labels.length === 0) return null;
    return { from: query.start, options: labels.map((label) => completionText(query, label)) };
  }
  if (!explicit) return null;
  const refs = upstream.map((item) => item.ref);
  if (refs.length === 0) return null;
  return { from: cursor, options: refs.map((ref) => `self.${ref}`) };
}

export function upstreamOutputs(
  nodeId: string,
  nodes: readonly { id: string; ref: string; name: string }[],
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
    .map((node) => ({
      ref: node.ref,
      name: node.name,
      paths: outputPaths(schemas.get(node.id)),
    }));
}

function completionText(query: CompletionQuery, label: string): string {
  if (query.kind === "ref") return `self.${label}`;
  return `self.${query.ref}.${label}`;
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
