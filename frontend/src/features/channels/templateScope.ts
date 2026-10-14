import type { SchemaObject } from "@/features/channels/configSchemaForm";

export type ScopeNodeOutput = {
  ref: string;
  name: string;
  schema: SchemaObject | null;
  sample: unknown;
};

export type ContextName = "channel" | "run" | "platform";

export type SelfScope = {
  nodes: readonly ScopeNodeOutput[];
  context: Record<ContextName, SchemaObject | null>;
};

export type AccessSegment = { kind: "attr"; name: string } | { kind: "key"; name: string };

export type AccessChain = {
  start: number;
  segments: AccessSegment[];
  filter: string;
};

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const IDENT_PREFIX = /^[A-Za-z_][A-Za-z0-9_]*/;
const CONTEXT_NAMES: readonly ContextName[] = ["channel", "run", "platform"];

export function children(schema: SchemaObject | null | undefined, sample: unknown): string[] {
  if (isArraySchema(schema)) return [];
  const declared = schema?.properties ? Object.keys(schema.properties).filter(isIdent) : [];
  const open = schema == null || schema.properties == null || schema.additionalProperties !== false;
  if (!open) return declared;
  const sampled = isPlainObject(sample) ? Object.keys(sample).filter(isIdent) : [];
  return [...declared, ...sampled.filter((key) => !declared.includes(key))];
}

export function child(
  schema: SchemaObject | null | undefined,
  sample: unknown,
  key: string,
): { schema: SchemaObject | null; sample: unknown } | null {
  if (isArraySchema(schema)) return null;
  const declared = schema?.properties?.[key];
  const closed = schema?.properties != null && schema.additionalProperties === false;
  if (closed && declared == null) return null;
  const nextSample = isPlainObject(sample) && key in sample ? sample[key] : undefined;
  if (declared == null && nextSample === undefined) return null;
  return { schema: declared ?? null, sample: nextSample };
}

export function parseAccess(text: string, cursor: number): AccessChain | null {
  const before = text.slice(0, cursor);
  let searchFrom = 0;
  let found: AccessChain | null = null;
  while (searchFrom < before.length) {
    const at = before.indexOf("self", searchFrom);
    if (at < 0) break;
    searchFrom = at + 1;
    if (at > 0 && isIdentChar(before[at - 1] ?? "")) continue;
    const parsed = parseFromSelf(before, at);
    if (parsed) found = { start: at, segments: parsed.segments, filter: parsed.filter };
  }
  return found;
}

export function memberOptions(scope: SelfScope, access: Pick<AccessChain, "segments" | "filter">): string[] {
  return membersAt(scope, access.segments).filter((name) => name.startsWith(access.filter));
}

function membersAt(scope: SelfScope, segments: readonly AccessSegment[]): string[] {
  if (segments.length === 0) {
    const refs = scope.nodes.map((node) => node.ref);
    const reserved = ["nodes", ...CONTEXT_NAMES].filter((name) => !refs.includes(name));
    return [...refs, ...reserved];
  }
  const head = segments[0];
  if (!head || head.kind !== "attr") return [];
  if (head.name === "nodes") return membersOfNodes(scope, segments.slice(1));
  if (isContextName(head.name)) return drill(scope.context[head.name], undefined, segments.slice(1));
  const node = scope.nodes.find((item) => item.ref === head.name);
  if (!node) return [];
  return membersOfOutput(node, segments.slice(1));
}

function membersOfNodes(scope: SelfScope, rest: readonly AccessSegment[]): string[] {
  const key = rest[0];
  if (!key || key.kind !== "key") return [];
  const node = scope.nodes.find((item) => item.name === key.name);
  if (!node) return [];
  return membersOfOutput(node, rest.slice(1));
}

function membersOfOutput(node: ScopeNodeOutput, rest: readonly AccessSegment[]): string[] {
  if (rest.length === 0) return ["output"];
  const first = rest[0];
  if (!first || first.kind !== "attr" || first.name !== "output") return [];
  return drill(node.schema, node.sample, rest.slice(1));
}

function drill(
  schema: SchemaObject | null | undefined,
  sample: unknown,
  rest: readonly AccessSegment[],
): string[] {
  if (rest.length === 0) return children(schema, sample);
  const segment = rest[0];
  if (!segment || segment.kind !== "attr") return [];
  const next = child(schema, sample, segment.name);
  if (!next) return [];
  return drill(next.schema, next.sample, rest.slice(1));
}

function parseFromSelf(
  before: string,
  start: number,
): { segments: AccessSegment[]; filter: string } | null {
  let index = start + "self".length;
  const segments: AccessSegment[] = [];
  while (index < before.length) {
    const char = before[index] ?? "";
    if (char === ".") {
      const name = readIdent(before, index + 1) ?? "";
      const next = index + 1 + name.length;
      if (next === before.length) return { segments, filter: name };
      if (!name) return null;
      const follower = before[next] ?? "";
      if (follower !== "." && follower !== "[") return null;
      segments.push({ kind: "attr", name });
      index = next;
      continue;
    }
    if (char === "[") {
      const key = readKey(before, index);
      if (!key) return null;
      segments.push({ kind: "key", name: key.name });
      index = key.end;
      continue;
    }
    return null;
  }
  return null;
}

function readIdent(text: string, start: number): string | null {
  const match = IDENT_PREFIX.exec(text.slice(start));
  return match ? match[0] : null;
}

function readKey(text: string, bracket: number): { name: string; end: number } | null {
  const quote = text[bracket + 1];
  if (quote !== "'" && quote !== '"') return null;
  let index = bracket + 2;
  let name = "";
  while (index < text.length) {
    if (text[index] === "\\") {
      name += text[index + 1] ?? "";
      index += 2;
      continue;
    }
    if (text[index] === quote) {
      if (text[index + 1] !== "]") return null;
      return { name, end: index + 2 };
    }
    name += text[index] ?? "";
    index += 1;
  }
  return null;
}

function isArraySchema(schema: SchemaObject | null | undefined): boolean {
  if (!schema) return false;
  const names = typeNames(schema).filter((name) => name !== "null");
  return names.length > 0 && names.every((name) => name === "array");
}

function typeNames(schema: SchemaObject): string[] {
  if (typeof schema.type === "string") return [schema.type];
  if (Array.isArray(schema.type)) return schema.type;
  return [];
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function isIdent(key: string): boolean {
  return IDENT.test(key);
}

function isIdentChar(char: string): boolean {
  return /[A-Za-z0-9_]/.test(char);
}

function isContextName(name: string): name is ContextName {
  return name === "channel" || name === "run" || name === "platform";
}
