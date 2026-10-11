import type { Graph, GraphEdge, GraphNode, GraphSettings } from "@/features/channels/types";

export type FlowNodeData = {
  nodeType: string;
  ref: string;
  name: string;
  config: Record<string, unknown>;
  onError: GraphNode["on_error"];
  retry: GraphNode["retry"];
  entry: boolean;
  problem: boolean;
};

export type FlowNodeShape = {
  id: string;
  position: { x: number; y: number };
  data: FlowNodeData;
};

export type FlowEdgeShape = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  problem?: boolean;
};

export type ClientProblemCode =
  | "CHANNEL_GRAPH_NO_TRIGGER"
  | "CHANNEL_GRAPH_TRIGGER_INPUT"
  | "CHANNEL_GRAPH_UNREACHABLE"
  | "CHANNEL_GRAPH_CYCLE";

export type ClientProblem = {
  code: ClientProblemCode;
  nodeId: string | null;
  edgeId: string | null;
};

const WHITE = 0;
const GRAY = 1;
const BLACK = 2;

export function newGraphId(prefix: "nd" | "ed"): string {
  const bytes = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  return `${prefix}_${bytes}`;
}

export function nodeRef(type: string, used: Iterable<string>): string {
  const base = type.replace(/\./g, "_").replace(/[^A-Za-z0-9_]/g, "") || "node";
  const taken = new Set(used);
  const reserved = new Set(["nodes", "channel", "run", "platform"]);
  let ref = base;
  let n = 2;
  while (taken.has(ref) || reserved.has(ref)) {
    ref = `${base}_${n}`;
    n += 1;
  }
  return ref;
}

export function emptyNodeData(
  nodeType: string,
  ref: string,
  name: string,
  config: Record<string, unknown>,
  entry: boolean,
): FlowNodeData {
  return {
    nodeType,
    ref,
    name,
    config,
    onError: "stop",
    retry: null,
    entry,
    problem: false,
  };
}

export function flowFromGraph(
  graph: Graph,
  entryTypes: ReadonlySet<string>,
): { nodes: FlowNodeShape[]; edges: FlowEdgeShape[] } {
  return {
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      position: node.position,
      data: {
        nodeType: node.type,
        ref: node.ref || nodeRef(node.type, graph.nodes.map((item) => item.ref).filter(Boolean)),
        name: node.name,
        config: node.config,
        onError: node.on_error,
        retry: node.retry,
        entry: entryTypes.has(node.type),
        problem: false,
      },
    })),
    edges: graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source.node_id,
      target: edge.target.node_id,
      sourceHandle: edge.source.port,
      targetHandle: edge.target.port,
    })),
  };
}

export function graphFromFlow(
  nodes: FlowNodeShape[],
  edges: FlowEdgeShape[],
  settings: GraphSettings,
): Graph {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      ref: node.data.ref,
      type: node.data.nodeType,
      name: node.data.name,
      position: { x: node.position.x, y: node.position.y },
      config: node.data.config,
      on_error: node.data.onError,
      retry: node.data.retry,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: { node_id: edge.source, port: edge.sourceHandle || "main" },
      target: { node_id: edge.target, port: edge.targetHandle || "main" },
    })),
    settings,
  };
}

export function clientGraphProblems(
  graph: Pick<Graph, "nodes" | "edges">,
  entryTypes: ReadonlySet<string>,
): ClientProblem[] {
  const problems: ClientProblem[] = [];
  const nodes = graph.nodes;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const triggers = nodes.filter((node) => entryTypes.has(node.type));
  if (triggers.length === 0) {
    problems.push({
      code: "CHANNEL_GRAPH_NO_TRIGGER",
      nodeId: null,
      edgeId: null,
    });
  }
  for (const edge of graph.edges) {
    const target = byId.get(edge.target.node_id);
    if (target && entryTypes.has(target.type)) {
      problems.push({
        code: "CHANNEL_GRAPH_TRIGGER_INPUT",
        nodeId: target.id,
        edgeId: edge.id,
      });
    }
  }
  problems.push(...unreachable(nodes, graph.edges, entryTypes));
  problems.push(...cycles(nodes, graph.edges, byId));
  return problems;
}

function unreachable(
  nodes: GraphNode[],
  edges: GraphEdge[],
  entryTypes: ReadonlySet<string>,
): ClientProblem[] {
  const outgoing = new Map<string, GraphEdge[]>();
  for (const edge of edges) {
    const list = outgoing.get(edge.source.node_id) ?? [];
    list.push(edge);
    outgoing.set(edge.source.node_id, list);
  }
  const seen = new Set<string>();
  const stack = nodes.filter((node) => entryTypes.has(node.type)).map((node) => node.id);
  while (stack.length > 0) {
    const nodeId = stack.pop()!;
    if (seen.has(nodeId)) continue;
    seen.add(nodeId);
    for (const edge of outgoing.get(nodeId) ?? []) {
      stack.push(edge.target.node_id);
    }
  }
  return nodes
    .filter((node) => !seen.has(node.id))
    .map((node) => ({
      code: "CHANNEL_GRAPH_UNREACHABLE" as const,
      nodeId: node.id,
      edgeId: null,
    }));
}

function cycles(
  nodes: GraphNode[],
  edges: GraphEdge[],
  byId: Map<string, GraphNode>,
): ClientProblem[] {
  const outgoing = new Map<string, GraphEdge[]>();
  for (const edge of edges) {
    if (!byId.has(edge.source.node_id) || !byId.has(edge.target.node_id)) continue;
    const list = outgoing.get(edge.source.node_id) ?? [];
    list.push(edge);
    outgoing.set(edge.source.node_id, list);
  }
  const color = new Map(nodes.map((node) => [node.id, WHITE]));
  const problems: ClientProblem[] = [];

  const dfs = (nodeId: string) => {
    color.set(nodeId, GRAY);
    for (const edge of outgoing.get(nodeId) ?? []) {
      const targetId = edge.target.node_id;
      if (color.get(targetId) === GRAY) {
        problems.push({
          code: "CHANNEL_GRAPH_CYCLE",
          nodeId: edge.source.node_id,
          edgeId: edge.id,
        });
      } else if (color.get(targetId) === WHITE) {
        dfs(targetId);
      }
    }
    color.set(nodeId, BLACK);
  };

  for (const node of nodes) {
    if (color.get(node.id) === WHITE) dfs(node.id);
  }
  return problems;
}

const PROBE_NODE_ID = "__probe_node__";
const PROBE_EDGE_ID = "__probe_edge__";

export type ConnectionCatalogItem = {
  type: string;
  entry: boolean;
  inputs: readonly { port: string }[];
  outputs: readonly { port: string }[];
};

export type ConnectionEnds = {
  source: string | null;
  target: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type ConnectionCandidate = {
  id: string;
  type: string;
};

function portName(handle: string | null | undefined): string {
  return handle ? handle : "main";
}

function problemIdentity(problem: ClientProblem): string {
  return `${problem.code}|${problem.nodeId ?? ""}|${problem.edgeId ?? ""}`;
}

function entryTypeSet(catalog: readonly ConnectionCatalogItem[]): Set<string> {
  return new Set(catalog.filter((item) => item.entry).map((item) => item.type));
}

export function connectionAllowed(
  graph: Pick<Graph, "nodes" | "edges">,
  catalog: readonly ConnectionCatalogItem[],
  connection: ConnectionEnds,
  candidate?: ConnectionCandidate,
): boolean {
  if (!connection.source || !connection.target) return false;
  if (connection.source === connection.target) return false;

  const byType = new Map(catalog.map((item) => [item.type, item]));
  const nodes: GraphNode[] = candidate
    ? [
        ...graph.nodes.filter((node) => node.id !== candidate.id),
        {
          id: candidate.id,
          ref: "probe",
          type: candidate.type,
          name: candidate.id,
          position: { x: 0, y: 0 },
          config: {},
          on_error: "stop",
          retry: null,
        },
      ]
    : graph.nodes;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const source = byId.get(connection.source);
  const target = byId.get(connection.target);
  if (!source || !target) return false;

  const sourceSpec = byType.get(source.type);
  const targetSpec = byType.get(target.type);
  if (!sourceSpec || !targetSpec) return false;
  if (targetSpec.entry) return false;

  const sourcePort = portName(connection.sourceHandle);
  const targetPort = portName(connection.targetHandle);
  if (!sourceSpec.outputs.some((port) => port.port === sourcePort)) return false;
  if (!targetSpec.inputs.some((port) => port.port === targetPort)) return false;

  const duplicate = graph.edges.some(
    (edge) =>
      edge.source.node_id === connection.source &&
      edge.target.node_id === connection.target &&
      edge.source.port === sourcePort &&
      edge.target.port === targetPort,
  );
  if (duplicate) return false;

  const entries = entryTypeSet(catalog);
  const before = new Set(clientGraphProblems(graph, entries).map(problemIdentity));
  const after = clientGraphProblems(
    {
      nodes,
      edges: [
        ...graph.edges,
        {
          id: PROBE_EDGE_ID,
          source: { node_id: connection.source, port: sourcePort },
          target: { node_id: connection.target, port: targetPort },
        },
      ],
    },
    entries,
  );
  return !after.some(
    (problem) =>
      (problem.code === "CHANNEL_GRAPH_TRIGGER_INPUT" || problem.code === "CHANNEL_GRAPH_CYCLE") &&
      !before.has(problemIdentity(problem)),
  );
}

export function outputTargetTypes<T extends ConnectionCatalogItem>(
  graph: Pick<Graph, "nodes" | "edges">,
  catalog: readonly T[],
  sourceId: string,
  sourceHandle: string | null,
): T[] {
  if (!graph.nodes.some((node) => node.id === sourceId)) return [];
  return catalog.filter((spec) =>
    spec.inputs.some((input) =>
      connectionAllowed(
        graph,
        catalog,
        {
          source: sourceId,
          target: PROBE_NODE_ID,
          sourceHandle,
          targetHandle: input.port,
        },
        { id: PROBE_NODE_ID, type: spec.type },
      ),
    ),
  );
}
