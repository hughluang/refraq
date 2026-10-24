import { describe, expect, it } from "vitest";

import { latestExecutionQuery } from "@/features/channels/datasetView";
import {
  ancestorIds,
  containerChain,
  executionCountByNode,
  executionScope,
  phaseByNode,
  roundControlIds,
  scopeRequest,
} from "@/features/channels/runSession";
import {
  EMPTY_GRAPH,
  type ChannelRunDetail,
  type Graph,
  type NodeSummary,
} from "@/features/channels/types";

function graph(): Graph {
  return {
    ...EMPTY_GRAPH,
    nodes: [
      {
        id: "trigger",
        ref: "run",
        type: "trigger.manual",
        name: "Run",
        position: { x: 0, y: 0 },
        config: {},
        on_error: "stop",
        retry: null,
      },
      {
        id: "body",
        ref: "step",
        type: "transform.set_fields",
        name: "Step",
        position: { x: 80, y: 0 },
        config: {},
        on_error: "stop",
        retry: null,
      },
      {
        id: "after",
        ref: "after",
        type: "write.entity",
        name: "After",
        position: { x: 160, y: 40 },
        config: {},
        on_error: "stop",
        retry: null,
      },
    ],
    edges: [
      {
        id: "e1",
        source: { node_id: "trigger", port: "main" },
        target: { node_id: "body", port: "main" },
      },
      {
        id: "e2",
        source: { node_id: "body", port: "main" },
        target: { node_id: "after", port: "main" },
      },
    ],
  };
}

function detail(status: string, summaries: readonly NodeSummary[]): ChannelRunDetail {
  return {
    run: { status, stop_at_node_id: null, job_id: "job_1" },
    graph: graph(),
    node_summaries: [...summaries],
  } as unknown as ChannelRunDetail;
}

describe("phaseByNode", () => {
  it("marks an unexecuted node dead once the run has finished", () => {
    const phases = phaseByNode(
      detail("succeeded", [
        { node_id: "trigger", execution_count: 1, status_counts: { succeeded: 1 } },
        { node_id: "body", execution_count: 1, status_counts: { succeeded: 1 } },
      ]),
      graph(),
    );
    expect(phases.get("body")).toBe("succeeded");
    expect(phases.get("after")).toBe("dead");
  });

  it("keeps a node waiting while the run is still going", () => {
    const phases = phaseByNode(detail("running", []), graph());
    expect(phases.get("after")).toBe("waiting");
  });

  it("uses the latest execution status when a node ran more than once", () => {
    const summary: NodeSummary = {
      node_id: "body",
      execution_count: 3,
      status_counts: { succeeded: 2, failed: 1 },
    };
    const phases = phaseByNode(detail("succeeded", [summary]), graph(), new Map([["body", "failed"]]));
    expect(phases.get("body")).toBe("failed");
    expect(latestExecutionQuery(summary)).toEqual({ node_id: "body", limit: 1, offset: 2 });
    expect(phaseByNode(detail("succeeded", [summary]), graph()).get("body")).toBe("waiting");
    expect(executionCountByNode([]).get("body")).toBeUndefined();
    expect(
      executionCountByNode([
        { node_id: "body", execution_count: 2, status_counts: { succeeded: 2 } },
        { node_id: "trigger", execution_count: 1, status_counts: { succeeded: 1 } },
      ]).get("body"),
    ).toBe(2);
  });
});

describe("sample scope", () => {
  const nodes = [
    { id: "outer", type: "volume.for" },
    { id: "inner", type: "volume.batch_read", parent: "outer" },
    { id: "body", type: "write.entity", parent: "inner" },
    { id: "after", type: "transform.set_fields" },
  ];

  it("walks containing frames from the outside in and omits the node itself", () => {
    expect(containerChain(nodes, "body")).toEqual(["outer", "inner"]);
    expect(containerChain(nodes, "inner")).toEqual(["outer"]);
    expect(containerChain(nodes, "after")).toEqual([]);
    expect(roundControlIds(nodes, "body")).toEqual(["outer", "inner"]);
    expect(roundControlIds(nodes, "inner")).toEqual(["outer", "inner"]);
    expect(roundControlIds(nodes, "after")).toEqual([]);
  });

  it("omits scope until a round is pinned, then sends the whole chain", () => {
    expect(scopeRequest(nodes, "body", {}, [])).toBeUndefined();
    expect(scopeRequest(nodes, "body", { inner: 2 }, [{ container_node_id: "outer", round: 1 }])).toEqual([
      { container_node_id: "outer", round: 1 },
      { container_node_id: "inner", round: 2 },
    ]);
    expect(scopeRequest(nodes, "after", { inner: 1 }, [])).toBeUndefined();
  });
});

describe("execution scope", () => {
  it("follows every outgoing edge without a stop and skips the body after done", () => {
    const base = graph();
    const loop: Graph = {
      ...base,
      nodes: [
        ...base.nodes.map((node) => (node.id === "body" ? { ...node, parent: "loop" } : node)),
        {
          id: "loop",
          ref: "walk",
          type: "volume.for",
          name: "Walk",
          position: { x: 40, y: 0 },
          config: {},
          on_error: "stop",
          retry: null,
        },
      ],
      edges: [
        {
          id: "to-loop",
          source: { node_id: "trigger", port: "main" },
          target: { node_id: "loop", port: "main" },
        },
        {
          id: "each",
          source: { node_id: "loop", port: "each" },
          target: { node_id: "body", port: "main" },
        },
        {
          id: "back",
          source: { node_id: "body", port: "main" },
          target: { node_id: "loop", port: "loop" },
        },
        {
          id: "done",
          source: { node_id: "loop", port: "done" },
          target: { node_id: "after", port: "main" },
        },
      ],
    };
    expect([...executionScope(loop, null)].sort()).toEqual(["after", "body", "loop", "trigger"]);
    expect(ancestorIds("body", loop.edges, loop.nodes).has("loop")).toBe(true);
    expect(ancestorIds("body", loop.edges, loop.nodes).has("trigger")).toBe(true);
    expect(ancestorIds("after", loop.edges, loop.nodes).has("body")).toBe(false);
    expect([...executionScope(loop, "after")].sort()).toEqual(["after", "loop", "trigger"]);
  });
});
