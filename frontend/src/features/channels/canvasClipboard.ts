import { canAuthorNodeType } from "@/features/channels/nodePermission";
import type { Graph, GraphEdge, GraphNode, GraphNote, NodeTypeSpec } from "@/features/channels/types";
import { newGraphId, nodeRef } from "@/features/channels/graphValidation";

export const FRAGMENT_KIND = "refraq.channel.fragment";
export const FRAGMENT_VERSION = 1;

export type ChannelFragment = {
  kind: typeof FRAGMENT_KIND;
  version: typeof FRAGMENT_VERSION;
  nodes: GraphNode[];
  edges: GraphEdge[];
  notes: GraphNote[];
};

export type PasteSkip = {
  trigger: number;
  permission: number;
  unknown: number;
  /** Permissions named by the nodes counted in `permission`, once each. */
  permissions: string[];
};

/** Nodes, edges, and notes to add. Empty when nothing was accepted. */
export type PasteResult = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  notes: GraphNote[];
  skipped: PasteSkip;
};

type CatalogItem = Pick<NodeTypeSpec, "type" | "trigger" | "permission">;

const DUPLICATE_OFFSET = 40;

export function serializeFragment(graph: Graph, selectedNodeIds: Iterable<string>): ChannelFragment {
  const selected = new Set(selectedNodeIds);
  const nodes = graph.nodes.filter((item) => selected.has(item.id)).map((item) => structuredClone(item));
  const edges = graph.edges
    .filter((item) => selected.has(item.source.node_id) && selected.has(item.target.node_id))
    .map((item) => structuredClone(item));
  const notes = (graph.notes ?? [])
    .filter((item) => selected.has(item.id))
    .map((item) => structuredClone(item));
  return {
    kind: FRAGMENT_KIND,
    version: FRAGMENT_VERSION,
    nodes,
    edges,
    notes,
  };
}

export function parseFragment(text: string): ChannelFragment | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;
  if (parsed.kind !== FRAGMENT_KIND || parsed.version !== FRAGMENT_VERSION) return null;
  if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges) || !Array.isArray(parsed.notes)) {
    return null;
  }
  const nodes: GraphNode[] = [];
  for (const item of parsed.nodes) {
    const node = parseNode(item);
    if (!node) return null;
    nodes.push(node);
  }
  const edges: GraphEdge[] = [];
  for (const item of parsed.edges) {
    const edge = parseEdge(item);
    if (!edge) return null;
    edges.push(edge);
  }
  const notes: GraphNote[] = [];
  for (const item of parsed.notes) {
    const note = parseNote(item);
    if (!note) return null;
    notes.push(note);
  }
  return {
    kind: FRAGMENT_KIND,
    version: FRAGMENT_VERSION,
    nodes,
    edges,
    notes,
  };
}

export function pasteFragment(
  fragment: ChannelFragment,
  graph: Pick<Graph, "nodes" | "edges">,
  catalog: readonly CatalogItem[],
  held: unknown,
  anchor: { x: number; y: number } | null,
): PasteResult {
  const byType = new Map(catalog.map((item) => [item.type, item]));
  const triggerTypes = new Set(catalog.filter((item) => item.trigger).map((item) => item.type));
  let triggerTaken = graph.nodes.some((item) => triggerTypes.has(item.type));
  const usedNames = new Set(graph.nodes.map((item) => item.name));
  const usedRefs = new Set(graph.nodes.map((item) => item.ref));
  const skipped: PasteSkip = { trigger: 0, permission: 0, unknown: 0, permissions: [] };
  const accepted: GraphNode[] = [];
  const idMap = new Map<string, string>();

  for (const source of fragment.nodes) {
    const spec = byType.get(source.type);
    if (!spec) {
      skipped.unknown += 1;
      continue;
    }
    if (spec.trigger && triggerTaken) {
      skipped.trigger += 1;
      continue;
    }
    const denied = spec.permission;
    if (denied && !canAuthorNodeType(denied, held)) {
      skipped.permission += 1;
      if (!skipped.permissions.includes(denied)) skipped.permissions.push(denied);
      continue;
    }
    if (spec.trigger) triggerTaken = true;
    const copy = structuredClone(source);
    copy.id = newGraphId("nd");
    copy.ref = nodeRef(source.ref, usedRefs);
    copy.name = nextName(source.name, usedNames);
    usedRefs.add(copy.ref);
    idMap.set(source.id, copy.id);
    accepted.push(copy);
  }

  const notes = fragment.notes.map((source) => ({
    ...structuredClone(source),
    id: newGraphId("nt"),
  }));
  const placed = placePasted(accepted, notes, anchor);
  const edges: GraphEdge[] = [];
  for (const source of fragment.edges) {
    const sourceId = idMap.get(source.source.node_id);
    const targetId = idMap.get(source.target.node_id);
    if (!sourceId || !targetId) continue;
    edges.push({
      id: newGraphId("ed"),
      source: { node_id: sourceId, port: source.source.port },
      target: { node_id: targetId, port: source.target.port },
    });
  }
  return { nodes: placed.nodes, edges, notes: placed.notes, skipped };
}

type Positioned = { position: { x: number; y: number } };

/** Anchor uses one origin for nodes and notes. No anchor shifts each item by the duplicate offset. */
function placePasted<N extends Positioned, M extends Positioned>(
  nodes: N[],
  notes: M[],
  anchor: { x: number; y: number } | null,
): { nodes: N[]; notes: M[] } {
  if (nodes.length === 0 && notes.length === 0) return { nodes, notes };
  if (!anchor) {
    return {
      nodes: shiftBy(nodes, DUPLICATE_OFFSET, DUPLICATE_OFFSET),
      notes: shiftBy(notes, DUPLICATE_OFFSET, DUPLICATE_OFFSET),
    };
  }
  const origin = boundsOrigin([...nodes, ...notes]);
  return {
    nodes: shiftBy(nodes, anchor.x - origin.x, anchor.y - origin.y),
    notes: shiftBy(notes, anchor.x - origin.x, anchor.y - origin.y),
  };
}

function boundsOrigin(items: readonly Positioned[]): { x: number; y: number } {
  return {
    x: Math.min(...items.map((item) => item.position.x)),
    y: Math.min(...items.map((item) => item.position.y)),
  };
}

function shiftBy<T extends Positioned>(items: T[], dx: number, dy: number): T[] {
  if (items.length === 0) return items;
  return items.map((item) => ({
    ...item,
    position: { x: item.position.x + dx, y: item.position.y + dy },
  }));
}

function nextName(name: string, used: Set<string>): string {
  if (!used.has(name)) {
    used.add(name);
    return name;
  }
  let index = 2;
  while (used.has(`${name} ${index}`)) index += 1;
  const next = `${name} ${index}`;
  used.add(next);
  return next;
}

function parseNote(value: unknown): GraphNote | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.text !== "string") return null;
  const position = parsePoint(value.position);
  const size = parseSize(value.size);
  if (!position || !size) return null;
  return { id: value.id, position, size, text: value.text };
}

function parsePoint(value: unknown): { x: number; y: number } | null {
  if (!isRecord(value) || typeof value.x !== "number" || typeof value.y !== "number") return null;
  return { x: value.x, y: value.y };
}

function parseSize(value: unknown): { width: number; height: number } | null {
  if (!isRecord(value) || typeof value.width !== "number" || typeof value.height !== "number") {
    return null;
  }
  return { width: value.width, height: value.height };
}

function parseNode(value: unknown): GraphNode | null {
  if (!isRecord(value)) return null;
  const { id, ref, type, name, position, config, on_error: onError, retry } = value;
  if (typeof id !== "string" || typeof ref !== "string") return null;
  if (typeof type !== "string" || typeof name !== "string") return null;
  if (!isRecord(position) || typeof position.x !== "number" || typeof position.y !== "number") {
    return null;
  }
  if (!isRecord(config)) return null;
  if (onError !== "stop" && onError !== "continue" && onError !== "error_output") return null;
  if (!isRetry(retry)) return null;
  const node: GraphNode = {
    id,
    ref,
    type,
    name,
    position: { x: position.x, y: position.y },
    config,
    on_error: onError,
    retry,
  };
  if ("type_version" in value) {
    if (typeof value.type_version !== "number") return null;
    node.type_version = value.type_version;
  }
  return node;
}

function parseEdge(value: unknown): GraphEdge | null {
  if (!isRecord(value) || typeof value.id !== "string") return null;
  const source = parseEnd(value.source);
  const target = parseEnd(value.target);
  if (!source || !target) return null;
  return { id: value.id, source, target };
}

function parseEnd(value: unknown): { node_id: string; port: string } | null {
  if (!isRecord(value) || typeof value.node_id !== "string" || typeof value.port !== "string") {
    return null;
  }
  return { node_id: value.node_id, port: value.port };
}

function isRetry(value: unknown): value is GraphNode["retry"] {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  return typeof value.max_tries === "number" && typeof value.wait_sec === "number";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
