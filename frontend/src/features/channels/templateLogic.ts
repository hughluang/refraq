import type { SchemaObject } from "@/features/channels/configSchemaForm";
import { crossesFrame } from "@/features/channels/frameLink";
import { scanTemplate, templatePosition } from "@/features/channels/templateScan";
import {
  memberOptions,
  parseAccess,
  type AccessChain,
  type ScopeNodeOutput,
  type SelfScope,
} from "@/features/channels/templateScope";

export type TemplateValueSchema = SchemaObject | { from: "entity_attribute" };

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
  if (schema["x-refraq-dataset-reference"] === true) {
    const names = typeNames(schema);
    if (names.includes("array")) return "list | dataset";
    return "dataset";
  }
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

export function templateCompletions(
  text: string,
  cursor: number,
  explicit: boolean,
  scope: SelfScope,
): TemplateCompletion | null {
  const position = templatePosition(text, cursor);
  if (position.kind === "outside" || position.kind === "string") return null;
  if (position.kind === "nodeKey") {
    const names = scope.nodes
      .map((item) => item.name)
      .filter((name) => name !== "" && name.startsWith(position.filter));
    if (names.length === 0) return null;
    return {
      from: position.start,
      options: names.map((name) => `self.nodes[${JSON.stringify(name)}]`),
    };
  }
  const access = parseAccess(text, cursor);
  if (access) {
    const members = memberOptions(scope, access);
    if (members.length === 0) return null;
    return {
      from: access.start,
      options: members.map((member) => applyMember(text, cursor, access, member)),
    };
  }
  if (!explicit) return null;
  return {
    from: cursor,
    options: memberOptions(scope, { segments: [], filter: "" }).map((name) => `self.${name}`),
  };
}

export type ScopeEdge = {
  source: string;
  target: string;
  /** Output port the edge leaves. Selects that port's refined schema. */
  sourcePort?: string;
  targetPort?: string;
};

export function upstreamOutputs(
  nodeId: string,
  nodes: readonly { id: string; ref: string; name: string; parent?: string | null }[],
  edges: readonly ScopeEdge[],
  schemas: ReadonlyMap<string, SchemaObject | null>,
  samples: ReadonlyMap<string, unknown> = new Map(),
): ScopeNodeOutput[] {
  const parentOf = new Map(nodes.map((node) => [node.id, node.parent]));
  const incoming = new Map<string, ScopeEdge[]>();
  for (const edge of edges) {
    if (crossesFrame(parentOf.get(edge.source), parentOf.get(edge.target), edge.source)) continue;
    const list = incoming.get(edge.target) ?? [];
    list.push(edge);
    incoming.set(edge.target, list);
  }
  const seen = new Set<string>();
  const portByNode = new Map<string, string | undefined>();
  const stack = [...(incoming.get(nodeId) ?? [])];
  while (stack.length > 0) {
    const edge = stack.pop();
    if (!edge || seen.has(edge.source)) continue;
    seen.add(edge.source);
    portByNode.set(edge.source, edge.sourcePort);
    stack.push(...(incoming.get(edge.source) ?? []));
  }
  return nodes
    .filter((node) => seen.has(node.id) && node.ref)
    .map((node) => ({
      ref: node.ref,
      name: node.name,
      schema: schemaAt(schemas, node.id, portByNode.get(node.id)),
      sample: samples.get(node.id),
    }));
}

function schemaAt(
  schemas: ReadonlyMap<string, SchemaObject | null>,
  nodeId: string,
  port: string | undefined,
): SchemaObject | null {
  if (port) {
    const keyed = schemas.get(`${nodeId}:${port}`);
    if (keyed !== undefined) return keyed;
  }
  const nodeSchema = schemas.get(nodeId);
  return nodeSchema === undefined ? null : nodeSchema;
}

function applyMember(text: string, cursor: number, access: AccessChain, member: string): string {
  const written = text.slice(access.start, cursor);
  return written.slice(0, written.length - access.filter.length) + member;
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
