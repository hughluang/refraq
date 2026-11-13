import ELK, { type ElkNode, type ElkPort } from "elkjs/lib/elk.bundled.js";

import {
  CARD_HEIGHT, CARD_WIDTH, EACH_INSET, FRAME_MIN_HEIGHT, FRAME_MIN_WIDTH, FRAME_PAD,
} from "@/features/channels/portLayout";

type Point = { x: number; y: number };
export type LayoutPort = {
  port: string;
  /** Exact handle offset from the node's top-left; otherwise evenly spaced. */
  offset?: Point;
};
export type LayoutNode = {
  id: string;
  parent?: string | null;
  position?: Point;
  /** Catalog declaration, not a node-type-name heuristic. */
  container?: object | null;
  width?: number;
  height?: number;
  /** Measured title/controls lane; at least LAYOUT_HEADER_HEIGHT is reserved. */
  headerHeight?: number;
  inputs: readonly LayoutPort[];
  outputs: readonly LayoutPort[];
};
export type LayoutEdge = {
  id: string;
  source: { node_id: string; port: string };
  target: { node_id: string; port: string };
};
export type LayoutPlacement = {
  id: string;
  parent?: string | null;
  position: Point;
  width: number;
  height: number;
};
export type LayoutResult = {
  status: "laid-out" | "invalid-parent";
  nodes: LayoutPlacement[];
};

/** Reserved title lane above direct children; frame trailing padding uses FRAME_PAD. */
export const LAYOUT_HEADER_HEIGHT = 64;

const options = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.randomSeed": "1",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.spacing.nodeNode": "48",
  "elk.layered.spacing.nodeNodeBetweenLayers": "72",
  "elk.spacing.componentComponent": "72",
  "elk.padding": "[top=0,left=0,bottom=0,right=0]",
};

/** Node placement only: no edge routes, graph data, notes, or execution priorities are rewritten. */
export async function layoutGraph(input: {
  nodes: readonly LayoutNode[];
  edges: readonly LayoutEdge[];
}): Promise<LayoutResult> {
  const nodes = [...input.nodes].sort((a, b) => compare(a.id, b.id));
  const edges = [...input.edges].sort((a, b) => compare(a.id, b.id));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  if (byId.size !== nodes.length) throw new Error("Layout requires unique node ids");
  const placements = new Map(nodes.map((node) => [node.id, {
    id: node.id,
    ...(node.parent !== undefined ? { parent: node.parent } : {}),
    position: { ...(node.position ?? { x: 0, y: 0 }) },
    width: dimension(node.width, node.container != null ? FRAME_MIN_WIDTH : CARD_WIDTH),
    height: dimension(node.height, node.container != null ? FRAME_MIN_HEIGHT : CARD_HEIGHT),
  }]));
  // A malformed hierarchy has no meaningful parent-relative solution. Keep it intact.
  for (const node of nodes) {
    const seen = new Set([node.id]);
    let parent = node.parent;
    while (parent) {
      const ancestor = byId.get(parent);
      if (!ancestor || ancestor.container == null || seen.has(parent)) {
        return { status: "invalid-parent", nodes: [...placements.values()] };
      }
      seen.add(parent);
      parent = ancestor.parent;
    }
  }

  const scopes = new Map<string | null, LayoutNode[]>();
  for (const node of nodes) {
    const scope = node.parent || null;
    scopes.set(scope, [...(scopes.get(scope) ?? []), node]);
  }
  const scopeEdges = new Map<string | null, LayoutEdge[]>();
  for (const edge of edges) {
    const source = byId.get(edge.source.node_id);
    const target = byId.get(edge.target.node_id);
    if (!source || !target ||
        !source.outputs.some((port) => port.port === edge.source.port) ||
        !target.inputs.some((port) => port.port === edge.target.port)) {
      continue;
    }
    const each = source.container != null && edge.source.port === "each";
    const enters = target.parent === source.id;
    if ((each && !enters) || (enters && !each) ||
        (!enters && (source.parent || null) !== (target.parent || null))) {
      continue;
    }
    const scope = target.parent || null;
    scopeEdges.set(scope, [...(scopeEdges.get(scope) ?? []), edge]);
  }

  const elk = new ELK();
  // Explicit postorder avoids recursive JS stack growth on deeply nested drafts.
  const pending: (string | null)[] = [null];
  const order: (string | null)[] = [];
  while (pending.length) {
    const scope = pending.pop()!;
    order.push(scope);
    for (const node of scopes.get(scope) ?? []) {
      if (node.container != null) pending.push(node.id);
    }
  }
  for (const scope of order.reverse()) {
    const members = scopes.get(scope) ?? [];
    const connections = scopeEdges.get(scope) ?? [];
    const header = Math.max(LAYOUT_HEADER_HEIGHT,
      dimension(scope === null ? undefined : byId.get(scope)!.headerHeight, LAYOUT_HEADER_HEIGHT));
    const ids = new Map(members.map((node, index) => [node.id, `n${index}`]));
    const ports = new Map<string, string>();
    const children: ElkNode[] = members.map((node) => {
      const size = placements.get(node.id)!;
      const id = ids.get(node.id)!;
      const enginePorts: ElkPort[] = [];
      for (const direction of ["inputs", "outputs"] as const) {
        const sidePorts = node[direction].filter((port) =>
          !(node.container != null && direction === "outputs" && port.port === "each"));
        sidePorts.forEach((port, index) => {
          const portId = `${id}p${enginePorts.length}`;
          ports.set(portKey(node.id, direction, port.port), portId);
          const offset = port.offset ?? {
            x: direction === "inputs" ? 0 : size.width,
            y: size.height * (index + 1) / (sidePorts.length + 1),
          };
          if (!Number.isFinite(offset.x) || !Number.isFinite(offset.y)) {
            throw new Error(`Invalid layout port geometry: ${node.id}/${port.port}`);
          }
          enginePorts.push({ id: portId, x: offset.x, y: offset.y, width: 0, height: 0,
            layoutOptions: { "elk.port.side": direction === "inputs" ? "WEST" : "EAST" } });
        });
      }
      return { id, width: size.width, height: size.height, ports: enginePorts,
        layoutOptions: { "elk.portConstraints": "FIXED_POS" } };
    });
    // The parent's inset each handle is an inlet to this scope, never a sibling frame edge.
    if (connections.some((edge) => edge.source.node_id === scope)) {
      children.push({ id: "inlet", width: 0, height: 0,
        ports: [{ id: "inlet-port", width: 0, height: 0,
          layoutOptions: { "elk.port.side": "EAST" } }],
        layoutOptions: { "elk.portConstraints": "FIXED_SIDE" } });
    }
    const laid = await elk.layout({ id: "scope", layoutOptions: options, children,
      edges: connections.map((edge, index) => ({ id: `e${index}`,
        sources: [edge.source.node_id === scope ? "inlet-port" : ports.get(portKey(edge.source.node_id, "outputs", edge.source.port))!],
        targets: [ports.get(portKey(edge.target.node_id, "inputs", edge.target.port))!],
      })),
    });
    let right = 0;
    let bottom = 0;
    for (const node of members) {
      const placed = laid.children?.find((child) => child.id === ids.get(node.id));
      if (!placed || !Number.isFinite(placed.x) || !Number.isFinite(placed.y)) {
        throw new Error(`ELK returned no finite placement for ${node.id}`);
      }
      const geometry = placements.get(node.id)!;
      geometry.position = { x: placed.x! + (scope === null ? 0 : FRAME_PAD),
        y: placed.y! + (scope === null ? 0 : header) };
      right = Math.max(right, geometry.position.x + geometry.width);
      bottom = Math.max(bottom, geometry.position.y + geometry.height);
    }
    if (scope !== null) {
      const frame = placements.get(scope)!;
      frame.width = Math.max(FRAME_MIN_WIDTH, frame.width, right + FRAME_PAD, EACH_INSET + FRAME_PAD);
      frame.height = Math.max(FRAME_MIN_HEIGHT, frame.height, bottom + FRAME_PAD, header + FRAME_PAD);
    }
  }
  return { status: "laid-out", nodes: [...placements.values()] };
}

function dimension(value: number | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  if (!Number.isFinite(value) || value <= 0) throw new Error("Layout dimensions must be finite and positive");
  return value;
}

function portKey(node: string, direction: string, port: string): string {
  return JSON.stringify([node, direction, port]);
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}
