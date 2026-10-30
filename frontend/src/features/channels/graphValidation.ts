import { omitUnsetIntegers, type SchemaObject } from "@/features/channels/configSchemaForm";
import type {
  ContainerDeclaration,
  Graph,
  GraphNode,
  GraphNote,
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
  trigger: boolean;
  /** `null` is not a Container. Empty `round_templates` is still a Container. */
  container: ContainerDeclaration | null;
  problem: boolean;
  typeVersion: number;
};

export type FlowNodeShape = {
  id: string;
  position: { x: number; y: number };
  data: FlowNodeData;
  /** Set only when the graph node has `parent`. React Flow's field; the graph field is `parent`. */
  parentId?: string;
};

export type FlowEdgeShape = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  problem?: boolean;
};

/** React Flow shape for a note. `data` is not `FlowNodeData`. */
export type FlowNoteShape = {
  id: string;
  position: { x: number; y: number };
  width: number;
  height: number;
  data: { text: string };
};

export function newGraphId(prefix: "nd" | "ed" | "nt"): string {
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
  trigger: boolean,
  container: ContainerDeclaration | null,
): FlowNodeData {
  return {
    nodeType,
    ref,
    name,
    config,
    onError: "stop",
    retry: null,
    trigger,
    container: copyContainer(container),
    problem: false,
    typeVersion: 1,
  };
}

function copyContainer(
  container: ContainerDeclaration | null | undefined,
): ContainerDeclaration | null {
  if (container == null) return null;
  return { round_templates: [...container.round_templates] };
}

export function flowFromGraph(
  graph: Graph,
  triggerTypes: ReadonlySet<string>,
  containers: ReadonlyMap<string, ContainerDeclaration | null> = new Map(),
): { nodes: FlowNodeShape[]; edges: FlowEdgeShape[]; notes: FlowNoteShape[] } {
  return {
    notes: (graph.notes ?? []).map((note) => ({
      id: note.id,
      position: { x: note.position.x, y: note.position.y },
      width: note.size.width,
      height: note.size.height,
      data: { text: note.text },
    })),
    nodes: graph.nodes.map((node) => {
      const flowNode: FlowNodeShape = {
        id: node.id,
        position: node.position,
        data: {
          nodeType: node.type,
          ref: node.ref || nodeRef(node.type, graph.nodes.map((item) => item.ref).filter(Boolean)),
          name: node.name,
          config: node.config,
          onError: node.on_error,
          retry: node.retry,
          trigger: triggerTypes.has(node.type),
          container: copyContainer(containers.get(node.type)),
          problem: false,
          typeVersion: node.type_version ?? 1,
        },
      };
      if (node.parent) flowNode.parentId = node.parent;
      return flowNode;
    }),
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
  notes: FlowNoteShape[] = [],
): Graph {
  const graph: Graph = {
    nodes: nodes.map((node) => {
      const graphNode: GraphNode = {
        id: node.id,
        ref: node.data.ref,
        type: node.data.nodeType,
        name: node.data.name,
        position: { x: node.position.x, y: node.position.y },
        config: node.data.config,
        on_error: node.data.onError,
        retry: node.data.retry,
        type_version: node.data.typeVersion ?? 1,
      };
      if (node.parentId) graphNode.parent = node.parentId;
      return graphNode;
    }),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: { node_id: edge.source, port: edge.sourceHandle || "main" },
      target: { node_id: edge.target, port: edge.targetHandle || "main" },
    })),
    settings,
  };
  if (notes.length > 0) graph.notes = notes.map(noteFromFlow);
  return graph;
}

function noteFromFlow(note: FlowNoteShape): GraphNote {
  return {
    id: note.id,
    position: { x: note.position.x, y: note.position.y },
    size: { width: note.width, height: note.height },
    text: note.data.text,
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

type InsertableSpec = ConnectionCatalogItem & { trigger?: boolean };

/** Types that can replace one edge: source reaches the type, and one of its outputs reaches the target. */
export function insertableTypes<T extends InsertableSpec>(
  graph: Pick<Graph, "nodes" | "edges">,
  catalog: readonly T[],
  edge: {
    source: { node_id: string; port: string };
    target: { node_id: string; port: string };
  },
): T[] {
  return catalog.filter((spec) => {
    if (spec.trigger) return false;
    const enters = spec.inputs.some((input) =>
      connectionAllowed(
        graph,
        catalog,
        {
          source: edge.source.node_id,
          target: PROBE_NODE_ID,
          sourceHandle: edge.source.port,
          targetHandle: input.port,
        },
        { id: PROBE_NODE_ID, type: spec.type },
      ),
    );
    if (!enters) return false;
    return spec.outputs.some((output) =>
      connectionAllowed(
        graph,
        catalog,
        {
          source: PROBE_NODE_ID,
          target: edge.target.node_id,
          sourceHandle: output.port,
          targetHandle: edge.target.port,
        },
        { id: PROBE_NODE_ID, type: spec.type },
      ),
    );
  });
}

/** Problems the server named as blocking a refused run or publish (`CHANNEL_GRAPH_INVALID`). */
export function refusedProblems(error: unknown): GraphProblem[] {
  if (!(error instanceof ApiError) || error.code !== "CHANNEL_GRAPH_INVALID") return [];
  const problems = error.extensions.problems;
  return Array.isArray(problems) ? (problems as GraphProblem[]) : [];
}
