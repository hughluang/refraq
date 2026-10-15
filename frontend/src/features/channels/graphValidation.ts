import { omitUnsetIntegers, type SchemaObject } from "@/features/channels/configSchemaForm";
import type {
  Graph,
  GraphNode,
  GraphProblem,
  GraphSettings,
  NodeTypeSpec,
} from "@/features/channels/types";
import { ApiError } from "@/lib/api";

export type FlowNodeData = {
  nodeType: string;
  ref: string;
  name: string;
  config: Record<string, unknown>;
  onError: GraphNode["on_error"];
  retry: GraphNode["retry"];
  entry: boolean;
  problem: boolean;
  typeVersion: number;
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
    typeVersion: 1,
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
        typeVersion: node.type_version ?? 1,
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

export function graphWithoutUnsetIntegers(
  graph: Graph,
  types: readonly Pick<NodeTypeSpec, "type" | "config_schema">[],
): Graph {
  const schemas = new Map(types.map((item) => [item.type, item.config_schema]));
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      const schema = schemas.get(node.type);
      if (!schema) return node;
      return { ...node, config: omitUnsetIntegers(node.config, schema as SchemaObject) };
    }),
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
      type_version: node.data.typeVersion ?? 1,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: { node_id: edge.source, port: edge.sourceHandle || "main" },
      target: { node_id: edge.target, port: edge.targetHandle || "main" },
    })),
    settings,
  };
}

const PROBE_NODE_ID = "__probe_node__";

export type ConnectionCatalogItem = {
  type: string;
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

export const VALIDATION_PAUSE_MS = 500;

export function validationContentKey(graph: Graph): string {
  return JSON.stringify({
    nodes: graph.nodes.map(({ position: _position, ...node }) => node),
    edges: graph.edges,
    settings: graph.settings,
  });
}

/** A draft load validates immediately. Later content edits wait out one pause. */
export function validationDelay(opened: boolean): number {
  return opened ? 0 : VALIDATION_PAUSE_MS;
}

export function validationResultApplies(validated: Graph, latest: Graph | null): boolean {
  return latest != null && validationContentKey(validated) === validationContentKey(latest);
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
  return !duplicate;
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

/** Problems the server named as blocking a refused run or publish (`CHANNEL_GRAPH_INVALID`). */
export function refusedProblems(error: unknown): GraphProblem[] {
  if (!(error instanceof ApiError) || error.code !== "CHANNEL_GRAPH_INVALID") return [];
  const problems = error.extensions.problems;
  return Array.isArray(problems) ? (problems as GraphProblem[]) : [];
}
