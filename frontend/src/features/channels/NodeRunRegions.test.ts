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
  "channels.run.notReached": "Not reached",
  "channels.run.waiting": "Waiting",
  "channels.run.running": "Running",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => LABELS[key] ?? key,
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
