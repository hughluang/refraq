/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listExecutions } from "@/features/channels/api";
import { ResultRegion, UpstreamRegion } from "@/features/channels/NodeRunRegions";
import { EMPTY_GRAPH, type ChannelRunDetail, type NodeExecution, type NodeSummary } from "@/features/channels/types";

vi.mock("@/features/channels/api", () => ({
  listExecutions: vi.fn(() => Promise.resolve({ items: [], total: 0, limit: 50, offset: 0 })),
  getExecutionOutput: vi.fn(),
  listDatasetRows: vi.fn(),
}));

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
  "channels.run.outputFailed": "Output failed",
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

function summariesFor(executions: { node_id: string }[]): NodeSummary[] {
  const grouped = new Map<string, number>();
  for (const item of executions) grouped.set(item.node_id, (grouped.get(item.node_id) ?? 0) + 1);
  return [...grouped].map(([node_id, execution_count]) => ({
    node_id,
    execution_count,
    status_counts: { succeeded: execution_count },
  }));
}

function detail(status: string, executions: NodeExecution[]): ChannelRunDetail {
  return {
    run: { status, stop_at_node_id: null, job_id: "job_1" },
    graph,
    node_summaries: summariesFor(executions),
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
    mount(createElement(ResultRegion, { channelId: "chn_1", nodeId: "b", detail: null }));
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("says the node has not executed when a finished run has no execution", () => {
    mount(createElement(ResultRegion, { channelId: "chn_1", nodeId: "b", detail: detail("failed", []) }));
    expect(screen.getByText("Absent")).toBeTruthy();
  });

  it("lists a page of executions for the node", async () => {
    const executions = [
      { seq: 2, node_id: "b", status: "succeeded", output_preview: { current: "a" } },
      { seq: 5, node_id: "b", status: "succeeded", output_preview: { current: "b" } },
    ] as NodeExecution[];
    vi.mocked(listExecutions).mockResolvedValue({
      items: executions,
      total: 2,
      limit: 50,
      offset: 0,
    });
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        nodeId: "b",
        detail: detail("succeeded", executions),
      }),
    );
    expect(await screen.findByText("2 executions")).toBeTruthy();
    expect(screen.getByText("Execution 2")).toBeTruthy();
    expect(screen.getByText("Execution 5")).toBeTruthy();
    expect(screen.getByText(/"current": "a"/)).toBeTruthy();
    expect(screen.getByText(/"current": "b"/)).toBeTruthy();
    expect(listExecutions).toHaveBeenCalledWith("chn_1", "job_1", {
      node_id: "b",
      limit: 50,
      offset: 0,
    });
  });

  it("shows waiting and running states", async () => {
    const executions = [{ seq: 1, node_id: "b", status: "running" }] as NodeExecution[];
    vi.mocked(listExecutions).mockResolvedValue({
      items: executions,
      total: 1,
      limit: 50,
      offset: 0,
    });
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        nodeId: "b",
        detail: detail("running", executions),
      }),
    );
    expect(await screen.findByText("Running")).toBeTruthy();
  });

  it("lists upstream output with its template path", async () => {
    const executions = [
      { seq: 1, node_id: "a", status: "succeeded", output_preview: { rows: [] } },
    ] as NodeExecution[];
    vi.mocked(listExecutions).mockResolvedValue({
      items: executions,
      total: 1,
      limit: 50,
      offset: 0,
    });
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("succeeded", executions),
      }),
    );
    expect(await screen.findByText("self.read.output")).toBeTruthy();
  });

  it("shows a load failure instead of an empty result", async () => {
    vi.mocked(listExecutions).mockRejectedValue(new Error("down"));
    const executions = [{ seq: 1, node_id: "b", status: "succeeded" }] as NodeExecution[];
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        nodeId: "b",
        detail: detail("succeeded", executions),
      }),
    );
    expect(await screen.findByText("Output failed")).toBeTruthy();
    expect(screen.queryByText("Absent")).toBeNull();
  });

  it("shows a load failure instead of an empty upstream", async () => {
    vi.mocked(listExecutions).mockRejectedValue(new Error("down"));
    const executions = [{ seq: 1, node_id: "a", status: "succeeded" }] as NodeExecution[];
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: detail("succeeded", executions),
      }),
    );
    expect(await screen.findByText("Output failed")).toBeTruthy();
    expect(screen.queryByText("No upstream output")).toBeNull();
  });

  it("reports a node with no upstream before any run", () => {
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        nodeId: "a",
        nodes,
        hasUpstream: false,
        detail: null,
      }),
    );
    expect(screen.getByText("No upstream")).toBeTruthy();
    expect(screen.queryByText("Idle")).toBeNull();
  });

  it("shows idle copy for a node with upstream before any run", () => {
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        nodeId: "b",
        nodes,
        hasUpstream: true,
        detail: null,
      }),
    );
    expect(screen.getByText("Idle")).toBeTruthy();
  });
});
