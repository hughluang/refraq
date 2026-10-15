import { describe, expect, it } from "vitest";

import {
  ancestorIds,
  executionCountByNode,
  executionScope,
  phaseByNode,
} from "@/features/channels/runSession";
import { EMPTY_GRAPH, type ChannelRunDetail, type Graph } from "@/features/channels/types";

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

function detail(status: string, executions: ChannelRunDetail["node_executions"]): ChannelRunDetail {
  return {
    run: { status, stop_at_node_id: null },
    graph: graph(),
    node_executions: executions,
  } as unknown as ChannelRunDetail;
}

describe("phaseByNode", () => {
  it("marks an unexecuted node dead once the run has finished", () => {
    const phases = phaseByNode(
      detail("succeeded", [
        { seq: 1, node_id: "trigger", status: "succeeded" },
        { seq: 2, node_id: "body", status: "succeeded" },
      ] as ChannelRunDetail["node_executions"]),
      graph(),
    );
    expect(phases.get("body")).toBe("succeeded");
    expect(phases.get("after")).toBe("dead");
  });

  it("keeps a node waiting while the run is still going", () => {
    const phases = phaseByNode(detail("running", []), graph());
    expect(phases.get("after")).toBe("waiting");
  });

  it("uses the latest execution when a node ran more than once", () => {
    const phases = phaseByNode(
      detail("succeeded", [
        { seq: 2, node_id: "body", status: "succeeded" },
        { seq: 4, node_id: "body", status: "failed" },
        { seq: 3, node_id: "body", status: "succeeded" },
      ] as ChannelRunDetail["node_executions"]),
      graph(),
    );
    expect(phases.get("body")).toBe("failed");
    expect(executionCountByNode(detail("succeeded", []).node_executions).get("body")).toBeUndefined();
    expect(
      executionCountByNode([
        { node_id: "body" },
        { node_id: "body" },
        { node_id: "trigger" },
      ]).get("body"),
    ).toBe(2);
  });
});

describe("execution scope", () => {
  it("includes a loop body and still closes on the stop node", () => {
    const loop: Graph = {
      ...graph(),
      nodes: [
        ...graph().nodes,
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
    expect(ancestorIds("body", loop.edges).has("loop")).toBe(true);
    expect(ancestorIds("after", loop.edges).has("body")).toBe(true);
  });
});
