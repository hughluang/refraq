import { describe, expect, it } from "vitest";

import {
  clientGraphProblems,
  connectionAllowed,
  flowFromGraph,
  graphFromFlow,
  outputTargetTypes,
  type ConnectionCatalogItem,
  type FlowNodeShape,
} from "@/features/channels/graphValidation";
import type { Graph } from "@/features/channels/types";

const ENTRY = new Set(["trigger.manual"]);

function node(id: string, type: string, name = id): Graph["nodes"][number] {
  return {
    id,
    type,
    name,
    position: { x: 1, y: 2 },
    config: {},
    on_error: "stop",
    retry: null,
  };
}

function edge(
  id: string,
  source: string,
  target: string,
  sourcePort = "main",
  targetPort = "main",
): Graph["edges"][number] {
  return {
    id,
    source: { node_id: source, port: sourcePort },
    target: { node_id: target, port: targetPort },
  };
}

function codes(graph: Pick<Graph, "nodes" | "edges">) {
  return clientGraphProblems(graph, ENTRY).map((problem) => problem.code);
}

describe("clientGraphProblems", () => {
  it("rejects a graph with no trigger", () => {
    expect(codes({ nodes: [node("nd_read", "read.entity")], edges: [] })).toEqual([
      "CHANNEL_GRAPH_NO_TRIGGER",
      "CHANNEL_GRAPH_UNREACHABLE",
    ]);
  });

  it("rejects a trigger input, an unreachable node, and a cycle", () => {
    const graph = {
      nodes: [
        node("nd_trigger", "trigger.manual"),
        node("nd_read", "read.entity"),
        node("nd_write", "write.entity"),
        node("nd_lone", "read.entity"),
      ],
      edges: [
        edge("ed_back", "nd_read", "nd_trigger"),
        edge("ed_1", "nd_trigger", "nd_read"),
        edge("ed_2", "nd_read", "nd_write"),
        edge("ed_3", "nd_write", "nd_read"),
      ],
    };
    const problems = clientGraphProblems(graph, ENTRY);
    expect(problems.some((item) => item.code === "CHANNEL_GRAPH_TRIGGER_INPUT" && item.nodeId === "nd_trigger")).toBe(true);
    expect(problems.some((item) => item.code === "CHANNEL_GRAPH_UNREACHABLE" && item.nodeId === "nd_lone")).toBe(true);
    expect(problems.some((item) => item.code === "CHANNEL_GRAPH_CYCLE")).toBe(true);
  });

  it("accepts a trigger connected to a read", () => {
    expect(
      codes({
        nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.entity")],
        edges: [edge("ed_1", "nd_trigger", "nd_read")],
      }),
    ).toEqual([]);
  });
});

describe("flow conversion", () => {
  it("round-trips node type, ports, and position", () => {
    const graph: Graph = {
      nodes: [
        {
          ...node("nd_trigger", "trigger.manual", "Run"),
          position: { x: 12, y: 34 },
          config: { entity_id: "ent_1" },
        },
      ],
      edges: [edge("ed_1", "nd_trigger", "nd_read", "error", "main")],
      settings: { run_timeout_sec: 30, error_channel_id: null },
    };
    const flow = flowFromGraph(graph, ENTRY);
    const restored = graphFromFlow(
      flow.nodes as FlowNodeShape[],
      flow.edges,
      graph.settings,
    );
    expect(restored.nodes[0]?.position).toEqual({ x: 12, y: 34 });
    expect(restored.nodes[0]?.config).toEqual({ entity_id: "ent_1" });
    expect(restored.nodes[0]?.type).toBe("trigger.manual");
    expect(restored.edges[0]).toEqual(edge("ed_1", "nd_trigger", "nd_read", "error", "main"));
    expect(restored.settings.run_timeout_sec).toBe(30);
    expect(flow.nodes[0]?.data.entry).toBe(true);
  });
});

const CATALOG: ConnectionCatalogItem[] = [
  { type: "trigger.manual", entry: true, inputs: [], outputs: [{ port: "main" }] },
  {
    type: "read.entity",
    entry: false,
    inputs: [{ port: "main" }],
    outputs: [{ port: "main" }, { port: "error" }],
  },
  {
    type: "write.entity",
    entry: false,
    inputs: [{ port: "main" }],
    outputs: [{ port: "main" }, { port: "error" }],
  },
];

describe("connectionAllowed", () => {
  const chain = {
    nodes: [
      node("nd_trigger", "trigger.manual"),
      node("nd_read", "read.entity"),
      node("nd_write", "write.entity"),
    ],
    edges: [
      edge("ed_1", "nd_trigger", "nd_read"),
      edge("ed_2", "nd_read", "nd_write"),
    ],
  };

  it("allows a trigger main output into a read", () => {
    expect(
      connectionAllowed(
        {
          nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.entity")],
          edges: [],
        },
        CATALOG,
        { source: "nd_trigger", target: "nd_read", sourceHandle: "main", targetHandle: "main" },
      ),
    ).toBe(true);
  });

  it("allows a read to a write when the graph has no trigger yet", () => {
    expect(
      connectionAllowed(
        { nodes: [node("nd_read", "read.entity"), node("nd_write", "write.entity")], edges: [] },
        CATALOG,
        { source: "nd_read", target: "nd_write", sourceHandle: "main", targetHandle: "main" },
      ),
    ).toBe(true);
  });

  it("rejects a self-loop, a trigger input, a duplicate, a missing port, and a cycle", () => {
    expect(
      connectionAllowed(
        { nodes: [node("nd_read", "read.entity")], edges: [] },
        CATALOG,
        { source: "nd_read", target: "nd_read", sourceHandle: "main", targetHandle: "main" },
      ),
    ).toBe(false);
    expect(
      connectionAllowed(
        {
          nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.entity")],
          edges: [],
        },
        CATALOG,
        { source: "nd_read", target: "nd_trigger", sourceHandle: "main", targetHandle: "main" },
      ),
    ).toBe(false);
    expect(
      connectionAllowed(chain, CATALOG, {
        source: "nd_trigger",
        target: "nd_read",
        sourceHandle: "main",
        targetHandle: "main",
      }),
    ).toBe(false);
    expect(
      connectionAllowed(
        {
          nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.entity")],
          edges: [],
        },
        CATALOG,
        { source: "nd_trigger", target: "nd_read", sourceHandle: "error", targetHandle: "main" },
      ),
    ).toBe(false);
    expect(
      connectionAllowed(chain, CATALOG, {
        source: "nd_write",
        target: "nd_read",
        sourceHandle: "main",
        targetHandle: "main",
      }),
    ).toBe(false);
  });

  it("lists node types that can accept an output", () => {
    const types = outputTargetTypes(
      { nodes: [node("nd_trigger", "trigger.manual")], edges: [] },
      CATALOG,
      "nd_trigger",
      "main",
    ).map((item) => item.type);
    expect(types).toEqual(["read.entity", "write.entity"]);
  });
});
