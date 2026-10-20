/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResultRegion, UpstreamRegion } from "@/features/channels/NodeRunRegions";
import { EMPTY_GRAPH, type ChannelRunDetail } from "@/features/channels/types";

const LABELS: Record<string, string> = {
  "channels.run.idle": "Idle",
  "channels.run.noUpstream": "No upstream",
  "channels.run.upstream": "Upstream outputs",
  "channels.run.result": "This node's result",
  "channels.run.running": "Running",
  "channels.run.executions": "{{count}} executions",
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

  it("says the node has not executed when a finished run has no execution", () => {
    mount(createElement(ResultRegion, { nodeId: "b", detail: detail("failed", []) }));
    expect(screen.getByText("Absent")).toBeTruthy();
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
});
