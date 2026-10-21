import { canAuthorNodeType } from "@/features/channels/nodePermission";
import type { Graph, GraphEdge, GraphNode, NodeTypeSpec } from "@/features/channels/types";
import { newGraphId, nodeRef } from "@/features/channels/graphValidation";

export const FRAGMENT_KIND = "refraq.channel.fragment";
export const FRAGMENT_VERSION = 1;

/** `notes` stays empty until channel notes are serialized. Parsed notes are kept for that slice. */
export type ChannelFragment = {
  kind: typeof FRAGMENT_KIND;
  version: typeof FRAGMENT_VERSION;
  nodes: GraphNode[];
  edges: GraphEdge[];
  notes: unknown[];
};

export type PasteSkip = {
  trigger: number;
  permission: number;
  unknown: number;
  /** Permissions named by the nodes counted in `permission`, once each. */
  permissions: string[];
};

/** Nodes and edges to add. Empty when every node was skipped. */
export type PasteResult = {
  nodes: GraphNode[];
  edges: GraphEdge[];
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
  return {
    kind: FRAGMENT_KIND,
    version: FRAGMENT_VERSION,
    nodes,
    edges,
    notes: [],
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
  return {
    kind: FRAGMENT_KIND,
    version: FRAGMENT_VERSION,
    nodes,
    edges,
    notes: parsed.notes,
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

  const nodes = placeNodes(accepted, anchor);
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
  return { nodes, edges, skipped };
}

function placeNodes(nodes: GraphNode[], anchor: { x: number; y: number } | null): GraphNode[] {
  if (nodes.length === 0) return nodes;
  if (!anchor) {
    return nodes.map((item) => ({
      ...item,
      position: { x: item.position.x + DUPLICATE_OFFSET, y: item.position.y + DUPLICATE_OFFSET },
    }));
  }
  const minX = Math.min(...nodes.map((item) => item.position.x));
  const minY = Math.min(...nodes.map((item) => item.position.y));
  return nodes.map((item) => ({
    ...item,
    position: {
      x: anchor.x + (item.position.x - minX),
      y: anchor.y + (item.position.y - minY),
    },
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
