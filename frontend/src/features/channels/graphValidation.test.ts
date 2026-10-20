import { describe, expect, it } from "vitest";

import {
  connectionAllowed,
  flowFromGraph,
  graphFromFlow,
  outputTargetTypes,
  VALIDATION_PAUSE_MS,
  validationContentKey,
  validationDelay,
  validationResultApplies,
  type ConnectionCatalogItem,
  type FlowNodeShape,
} from "@/features/channels/graphValidation";
import type { Graph } from "@/features/channels/types";

const TRIGGERS = new Set(["trigger.manual"]);

function node(id: string, type: string, name = id): Graph["nodes"][number] {
  return {
    id,
    ref: id,
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
    const flow = flowFromGraph(graph, TRIGGERS);
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
    expect(flow.nodes[0]?.data.trigger).toBe(true);
  });
});

const CATALOG: ConnectionCatalogItem[] = [
  { type: "trigger.manual", inputs: [], outputs: [{ port: "main" }] },
  {
    type: "read.sql",
    inputs: [{ port: "main" }],
    outputs: [{ port: "main" }, { port: "error" }],
  },
  {
    type: "write.entity",
    inputs: [{ port: "main" }],
    outputs: [{ port: "main" }, { port: "error" }],
  },
];

describe("connectionAllowed", () => {
  const chain = {
    nodes: [
      node("nd_trigger", "trigger.manual"),
      node("nd_read", "read.sql"),
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
          nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.sql")],
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
        { nodes: [node("nd_read", "read.sql"), node("nd_write", "write.entity")], edges: [] },
        CATALOG,
        { source: "nd_read", target: "nd_write", sourceHandle: "main", targetHandle: "main" },
      ),
    ).toBe(true);
  });

  it("rejects a self-loop, a duplicate, and a missing port", () => {
    expect(
      connectionAllowed(
        { nodes: [node("nd_read", "read.sql")], edges: [] },
        CATALOG,
        { source: "nd_read", target: "nd_read", sourceHandle: "main", targetHandle: "main" },
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
          nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.sql")],
          edges: [],
        },
        CATALOG,
        { source: "nd_trigger", target: "nd_read", sourceHandle: "error", targetHandle: "main" },
      ),
    ).toBe(false);
  });

  it("allows a cycle and a connection into a trigger input", () => {
    const triggerWithInput: ConnectionCatalogItem[] = [
      { type: "trigger.manual", inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
      ...CATALOG.filter((item) => item.type !== "trigger.manual"),
    ];
    expect(
      connectionAllowed(
        {
          nodes: [node("nd_trigger", "trigger.manual"), node("nd_read", "read.sql")],
          edges: [],
        },
        triggerWithInput,
        { source: "nd_read", target: "nd_trigger", sourceHandle: "main", targetHandle: "main" },
      ),
    ).toBe(true);
    expect(
      connectionAllowed(chain, CATALOG, {
        source: "nd_write",
        target: "nd_read",
        sourceHandle: "main",
        targetHandle: "main",
      }),
    ).toBe(true);
  });

  it("allows a cycle through a loop-back port and several edges into one input", () => {
    const catalog: ConnectionCatalogItem[] = [
      ...CATALOG,
      {
        type: "volume.for",
        inputs: [{ port: "main" }, { port: "loop" }],
        outputs: [{ port: "each" }, { port: "done" }],
      },
      {
        type: "transform.merge",
        inputs: [{ port: "main" }],
        outputs: [{ port: "main" }],
      },
      {
        type: "transform.if",
        inputs: [{ port: "main" }],
        outputs: [{ port: "true" }, { port: "false" }],
      },
    ];
    const nodes = [
      node("nd_for", "volume.for"),
      node("nd_body", "read.sql"),
      node("nd_left", "read.sql"),
      node("nd_right", "read.sql"),
      node("nd_merge", "transform.merge"),
    ];
    expect(
      connectionAllowed(
        {
          nodes,
          edges: [edge("ed_each", "nd_for", "nd_body", "each", "main")],
        },
        catalog,
        {
          source: "nd_body",
          target: "nd_for",
          sourceHandle: "main",
          targetHandle: "loop",
        },
      ),
    ).toBe(true);
    const merged = {
      nodes,
      edges: [edge("ed_left", "nd_left", "nd_merge")],
    };
    expect(
      connectionAllowed(merged, catalog, {
        source: "nd_right",
        target: "nd_merge",
        sourceHandle: "main",
        targetHandle: "main",
      }),
    ).toBe(true);
    expect(
      outputTargetTypes({ nodes: [node("nd_if", "transform.if")], edges: [] }, catalog, "nd_if", "true").map(
        (item) => item.type,
      ),
    ).toContain("read.sql");
  });

  it("lists node types that can accept an output", () => {
    const types = outputTargetTypes(
      { nodes: [node("nd_trigger", "trigger.manual")], edges: [] },
      CATALOG,
      "nd_trigger",
      "main",
    ).map((item) => item.type);
    expect(types).toEqual(["read.sql", "write.entity"]);
  });
});

describe("validation schedule keys", () => {
  const settings = { run_timeout_sec: null, error_channel_id: null };

  it("ignores position when comparing content", () => {
    const graph: Graph = {
      nodes: [node("nd_read", "read.sql", "Read")],
      edges: [],
      settings,
    };
    const moved: Graph = {
      ...graph,
      nodes: [{ ...graph.nodes[0]!, position: { x: 9, y: 9 } }],
    };
    expect(validationContentKey(graph)).toBe(validationContentKey(moved));
  });

  it("validates a loaded draft immediately and later content after a pause", () => {
    const graph: Graph = {
      nodes: [node("nd_read", "read.sql", "Read")],
      edges: [],
      settings,
    };
    const renamed: Graph = {
      ...graph,
      nodes: [{ ...graph.nodes[0]!, name: "Suppliers" }],
    };
    const added: Graph = {
      ...graph,
      nodes: [...graph.nodes, node("nd_write", "write.entity", "Write")],
    };
    const first = validationContentKey(graph);
    expect(validationContentKey(renamed)).not.toBe(first);
    expect(validationContentKey(added)).not.toBe(first);

    expect(validationDelay(true)).toBe(0);
    expect(validationDelay(false)).toBe(VALIDATION_PAUSE_MS);
  });

  it("drops a validation result after the graph content has moved on", () => {
    const settings = { run_timeout_sec: null, error_channel_id: null };
    const broken: Graph = {
      nodes: [node("nd_read", "read.sql", "")],
      edges: [],
      settings,
    };
    const fixed: Graph = {
      ...broken,
      nodes: [{ ...broken.nodes[0]!, name: "Suppliers" }],
    };
    const moved: Graph = {
      ...fixed,
      nodes: [{ ...fixed.nodes[0]!, position: { x: 40, y: 80 } }],
    };

    expect(validationResultApplies(broken, fixed)).toBe(false);
    expect(validationResultApplies(fixed, null)).toBe(false);
    expect(validationResultApplies(fixed, moved)).toBe(true);
    expect(validationResultApplies(moved, fixed)).toBe(true);
  });
});
