/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NodeRunSummary, ResultRegion, UpstreamRegion } from "@/features/channels/NodeRunRegions";
import { EMPTY_GRAPH, type ChannelRunDetail } from "@/features/channels/types";

const LABELS: Record<string, string> = {
  "channels.run.idle": "Idle",
  "channels.run.noUpstream": "No upstream",
  "channels.run.upstream": "Upstream outputs",
  "channels.run.result": "This node's result",
  "channels.run.notReached": "Not reached",
  "channels.run.waiting": "Waiting",
  "channels.run.running": "Running",
  "channels.run.executions": "{{count}} executions",
  "channels.node.moreUpstream": "{{count}} more upstream nodes",
  "channels.run.execution": "Execution {{seq}}",
  "channels.run.empty": "No upstream output",
  "channels.run.absent": "Absent",
  "channels.canvas.phase.waiting": "Waiting short",
  "channels.editor.status.succeeded": "Succeeded",
  "channels.editor.status.failed": "Failed",
  "channels.editor.status.running": "Running phase",
  "channels.run.notRun": "Not run",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
}));

const graph = {
  ...EMPTY_GRAPH,
  nodes: [
    { id: "a", ref: "read", name: "Read", type: "trigger.manual", config: {} },
    { id: "b", ref: "write", name: "Write", type: "x", config: {} },
  ],
  edges: [{ id: "e", source: { node_id: "a", port: "main" }, target: { node_id: "b", port: "main" } }],
} as unknown as ChannelRunDetail["graph"];

function detail(status: string, executions: unknown[]): ChannelRunDetail {
  return {
    run: { status, stop_at_node_id: null },
    graph,
    node_executions: executions,
  } as unknown as ChannelRunDetail;
}

const nodes = [
  { id: "a", ref: "read", name: "Read" },
  { id: "b", ref: "write", name: "Write" },
];

function mount(node: ReturnType<typeof createElement>) {
  render(createElement(MantineProvider, { env: "test" }, node));
}

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
});

afterEach(cleanup);

describe("node run regions", () => {
  it("shows idle copy without a run", () => {
    mount(createElement(ResultRegion, { nodeId: "b", detail: null }));
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("says not reached once a finished run skipped the node", () => {
    mount(createElement(ResultRegion, { nodeId: "b", detail: detail("failed", []) }));
    expect(screen.getByText("Not reached")).toBeTruthy();
  });

  it("lists every execution of a node and the count", () => {
    mount(
      createElement(ResultRegion, {
        nodeId: "b",
        detail: detail("succeeded", [
          { seq: 2, node_id: "b", status: "succeeded", output_preview: { current: "a" } },
          { seq: 5, node_id: "b", status: "succeeded", output_preview: { current: "b" } },
        ]),
      }),
    );
    expect(screen.getByText("2 executions")).toBeTruthy();
    expect(screen.getByText("Execution 2")).toBeTruthy();
    expect(screen.getByText("Execution 5")).toBeTruthy();
    expect(screen.getByText(/"current": "a"/)).toBeTruthy();
    expect(screen.getByText(/"current": "b"/)).toBeTruthy();
  });

  it("shows waiting and running states", () => {
    mount(
      createElement(ResultRegion, {
        nodeId: "b",
        detail: detail("running", [{ seq: 1, node_id: "b", status: "running" }]),
      }),
    );
    expect(screen.getByText("Running")).toBeTruthy();
  });

  it("lists upstream output with its template path", () => {
    mount(
      createElement(UpstreamRegion, {
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("succeeded", [
          { seq: 1, node_id: "a", status: "succeeded", output_preview: { rows: [] } },
        ]),
      }),
    );
    expect(screen.getByText("self.read.output")).toBeTruthy();
  });

  it("reports a node with no upstream before any run", () => {
    mount(createElement(UpstreamRegion, { nodeId: "a", nodes, hasUpstream: false, detail: null }));
    expect(screen.getByText("No upstream")).toBeTruthy();
    expect(screen.queryByText("Idle")).toBeNull();
  });

  it("shows idle copy for a node with upstream before any run", () => {
    mount(createElement(UpstreamRegion, { nodeId: "b", nodes, hasUpstream: true, detail: null }));
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("uses the idle and no-upstream sentences before a run", () => {
    mount(
      createElement(NodeRunSummary, {
        nodeId: "a",
        nodes,
        hasUpstream: false,
        detail: null,
      }),
    );
    expect(screen.getByText("Upstream outputs: No upstream")).toBeTruthy();
    expect(screen.getByText("This node's result: Idle")).toBeTruthy();
  });

  it("names an upstream node and its phase instead of rendering output", () => {
    mount(
      createElement(NodeRunSummary, {
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("succeeded", [
          { seq: 1, node_id: "a", status: "succeeded", output_preview: { rows: ["secret"] } },
        ]),
      }),
    );
    expect(screen.getByText("Upstream outputs: Read Succeeded")).toBeTruthy();
    expect(screen.queryByText(/secret/)).toBeNull();
  });

  it("names this node and its phase instead of rendering its output", () => {
    mount(
      createElement(NodeRunSummary, {
        nodeId: "a",
        nodes,
        hasUpstream: false,
        detail: detail("succeeded", [
          { seq: 1, node_id: "a", status: "succeeded", output_preview: { rows: ["secret"] } },
        ]),
      }),
    );
    expect(screen.getByText("Upstream outputs: No upstream")).toBeTruthy();
    expect(screen.getByText("This node's result: Read Succeeded")).toBeTruthy();
    expect(screen.queryByText(/secret/)).toBeNull();
  });

  it("keeps the waiting, not-reached, and running sentences", () => {
    mount(
      createElement(NodeRunSummary, {
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("running", []),
      }),
    );
    expect(screen.getByText("Upstream outputs: No upstream output")).toBeTruthy();
    expect(screen.getByText("This node's result: Waiting")).toBeTruthy();

    cleanup();
    mount(
      createElement(NodeRunSummary, {
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("failed", []),
      }),
    );
    expect(screen.getByText("This node's result: Not reached")).toBeTruthy();

    cleanup();
    mount(
      createElement(NodeRunSummary, {
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("running", [{ seq: 1, node_id: "b", status: "running" }]),
      }),
    );
    expect(screen.getByText("This node's result: Running")).toBeTruthy();
    expect(screen.queryByText("Running phase")).toBeNull();
  });

  it("lists at most three upstream nodes and counts the rest", () => {
    const chain = {
      nodes: [
        { id: "a", ref: "a", name: "Alpha", type: "trigger.manual", config: {} },
        { id: "c", ref: "c", name: "Beta", type: "x", config: {} },
        { id: "d", ref: "d", name: "Gamma", type: "x", config: {} },
        { id: "e", ref: "e", name: "Delta", type: "x", config: {} },
        { id: "b", ref: "b", name: "Write", type: "x", config: {} },
      ],
      edges: [
        edge("a", "c"),
        edge("c", "d"),
        edge("d", "e"),
        edge("e", "b"),
      ],
    };
    const listed = chain.nodes.map((node) => ({ id: node.id, ref: node.ref, name: node.name }));
    mount(
      createElement(NodeRunSummary, {
        nodeId: "b",
        nodes: listed,
        hasUpstream: true,
        detail: {
          run: { status: "succeeded", stop_at_node_id: null },
          graph: chain,
          node_executions: [
            { seq: 1, node_id: "a", status: "succeeded", output_preview: { n: 1 } },
            { seq: 2, node_id: "c", status: "succeeded", output_preview: { n: 2 } },
            { seq: 3, node_id: "d", status: "succeeded", output_preview: { n: 3 } },
            { seq: 4, node_id: "e", status: "failed", output_preview: { n: 4 } },
          ],
        } as unknown as ChannelRunDetail,
      }),
    );
    expect(screen.getByText("Upstream outputs: Alpha Succeeded")).toBeTruthy();
    expect(screen.getByText("Beta Succeeded")).toBeTruthy();
    expect(screen.getByText("Gamma Succeeded")).toBeTruthy();
    expect(screen.queryByText(/Delta/)).toBeNull();
    expect(screen.queryByText("1 executions")).toBeNull();
    expect(screen.getByText("1 more upstream nodes")).toBeTruthy();
    expect(screen.queryByText(/"n":/)).toBeNull();
  });
});

function edge(source: string, target: string) {
  return {
    id: `${source}-${target}`,
    source: { node_id: source, port: "main" },
    target: { node_id: target, port: "main" },
  };
}
