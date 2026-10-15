/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_GRAPH,
  type ChannelRunDetail,
  type Graph,
  type GraphProblem,
  type NodeTypeSpec,
} from "@/features/channels/types";
import { Instant } from "@/lib/instant";

const LABELS: Record<string, string> = {
  "channels.canvas.add": "Add",
  "channels.canvas.undo": "Undo",
  "channels.canvas.redo": "Redo",
  "channels.canvas.palette": "Nodes",
  "channels.canvas.problemsSummary": "{{errors}} errors, {{warnings}} warnings",
  "channels.node.run": "Run node",
  "channels.node.config": "Configuration",
  "channels.run.upstream": "Upstream outputs",
  "channels.run.result": "This node's result",
  "channels.run.waiting": "Waiting for this node",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const fallback = typeof options?.defaultValue === "string" ? options.defaultValue : key;
    const template = LABELS[key] ?? fallback;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
}));

function stubDomApis() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
  if (!SVGElement.prototype.getBBox) {
    SVGElement.prototype.getBBox = () => ({
      x: 0,
      y: 0,
      width: 0,
      height: 0,
      bottom: 0,
      left: 0,
      right: 0,
      top: 0,
      toJSON: () => ({}),
    });
  }
}

const spec: NodeTypeSpec = {
  type: "manual",
  family: "trigger",
  label: "Manual",
  summary: "Start here",
  description: "",
  entry: true,
  inputs: [],
  outputs: [{ port: "out", description: "" }],
  config_schema: {},
  permission: null,
};

const nodeGraph: Graph = {
  nodes: [
    {
      id: "nd_1",
      ref: "manual",
      type: "manual",
      name: "Start",
      position: { x: 40, y: 40 },
      config: {},
      on_error: "stop",
      retry: null,
    },
  ],
  edges: [],
  settings: EMPTY_GRAPH.settings,
};

function renderCanvas(
  problems: GraphProblem[] = [],
  graph: Graph = EMPTY_GRAPH,
  options: {
    appearance?: "edit" | "browse";
    mutable?: boolean;
    sessionRun?: ChannelRunDetail | null;
    onRun?: (nodeId: string) => void;
  } = {},
) {
  const appearance = options.appearance ?? "edit";
  const mutable = options.mutable ?? appearance === "edit";
  return import("@/features/channels/ChannelCanvas").then(({ ChannelCanvas }) => {
    const element = (next: GraphProblem[]) =>
        createElement(
          MantineProvider,
          { env: "test" },
          createElement(ChannelCanvas, {
          graph,
          catalog: [spec],
          appearance,
          mutable,
          problems: next,
          onChange: vi.fn(),
          sessionRun: options.sessionRun,
          onRun: options.onRun,
        }),
      );
    const view = render(element(problems));
    return {
      rerenderProblems(next: GraphProblem[]) {
        view.rerender(element(next));
      },
    };
  });
}

describe("ChannelCanvas controls", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("puts add, undo, and redo in the control panel and drops zoom", async () => {
    await renderCanvas();

    const panel = screen.getByTestId("rf__controls");
    expect(document.querySelector(".channel-canvas-stage--browse")).toBeNull();
    expect(panel.querySelector(".react-flow__controls-zoomin")).toBeNull();
    expect(panel.querySelector(".react-flow__controls-zoomout")).toBeNull();
    expect(panel.querySelector(".react-flow__controls-fitview")).not.toBeNull();
    expect(panel.querySelector(".react-flow__controls-interactive")).not.toBeNull();

    const add = screen.getByRole("button", { name: "Add" });
    const undo = screen.getByRole("button", { name: "Undo" });
    const redo = screen.getByRole("button", { name: "Redo" });
    expect(add.querySelector("svg")).not.toBeNull();
    expect(add.textContent).toBe("");
    expect(panel.contains(add)).toBe(true);
    expect(panel.contains(undo)).toBe(true);
    expect(panel.contains(redo)).toBe(true);
    expect((undo as HTMLButtonElement).disabled).toBe(true);
    expect((redo as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /problems/ })).toBeNull();

    fireEvent.click(add);
    expect(add.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Nodes")).toBeTruthy();
    expect(screen.getByText("Manual")).toBeTruthy();
  });

  it("drops the dot grid and authoring controls while browsing", async () => {
    await renderCanvas(
      [{ code: "graph.empty", node_id: null, edge_id: null, path: [], detail: "Empty graph" }],
      nodeGraph,
      { appearance: "browse", mutable: false },
    );

    const panel = screen.getByTestId("rf__controls");
    expect(document.querySelector(".channel-canvas-stage--browse")).not.toBeNull();
    expect(document.querySelector(".react-flow__background")).toBeNull();
    expect(document.querySelector(".react-flow__handle")).not.toBeNull();
    expect(panel.querySelector(".react-flow__controls-fitview")).not.toBeNull();
    expect(panel.querySelector(".react-flow__controls-interactive")).toBeNull();
    expect(screen.getByRole("button", { name: "1 errors, 0 warnings" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Redo" })).toBeNull();

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    expect(screen.getByRole("region", { name: "Configuration" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run node" })).toBeNull();
  });

  it("puts the problem control in the panel with a count badge", async () => {
    await renderCanvas([
      { code: "graph.empty", node_id: null, edge_id: null, path: [], detail: "Empty graph" },
    ]);

    const problems = screen.getByRole("button", { name: "1 errors, 0 warnings" });
    const panel = screen.getByTestId("rf__controls");
    expect(panel.contains(problems)).toBe(true);
    expect(problems.querySelector(".channel-canvas-problems__badge")?.textContent).toBe("1");
  });

  it("highlights a node only after its problem is chosen", async () => {
    const view = await renderCanvas(
      [{ code: "graph.empty", node_id: "nd_1", edge_id: null, path: [], detail: "Empty graph" }],
      nodeGraph,
    );
    expect(document.querySelector(".channel-flow-node--problem")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "1 errors, 0 warnings" }));
    fireEvent.click(screen.getByRole("button", { name: "Empty graph (Start)" }));
    expect(document.querySelector(".channel-flow-node--problem")).not.toBeNull();
    expect(screen.getByRole("button", { name: "channels.node.close" })).toBeTruthy();
    expect(screen.getByText("Empty graph")).toBeTruthy();
    expect(document.querySelector(".channel-node-detail")?.textContent ?? "").not.toContain(
      "Empty graph",
    );

    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");
    fireEvent.click(pane);
    expect(document.querySelector(".channel-flow-node--problem")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "1 errors, 0 warnings" }));
    fireEvent.click(screen.getByRole("button", { name: "Empty graph (Start)" }));
    expect(document.querySelector(".channel-flow-node--problem")).not.toBeNull();

    view.rerenderProblems([]);
    await waitFor(() => {
      expect(document.querySelector(".channel-flow-node--problem")).toBeNull();
    });
  });

  it("hides the problem control when the open list is cleared", async () => {
    const view = await renderCanvas([
      { code: "graph.empty", node_id: null, edge_id: null, path: [], detail: "Empty graph" },
      { code: "graph.other", node_id: null, edge_id: null, path: [], detail: "Other" },
    ]);

    const problems = screen.getByRole("button", { name: "2 errors, 0 warnings" });
    fireEvent.click(problems);
    expect(problems.getAttribute("aria-expanded")).toBe("true");
    expect(problems.querySelector(".channel-canvas-problems__badge")?.textContent).toBe("2");

    view.rerenderProblems([]);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /errors/ })).toBeNull();
    });
  });

  it("shows a warning-only list in the warning tone", async () => {
    await renderCanvas(
      [
        {
          code: "CHANNEL_TEMPLATE_TYPE_UNKNOWN",
          node_id: "nd_1",
          edge_id: null,
          path: [],
          detail: "Checked at run time",
          severity: "warning",
        },
      ],
      nodeGraph,
    );

    const problems = screen.getByRole("button", { name: "0 errors, 1 warnings" });
    expect(problems.className).toContain("channel-canvas-problems--warning");
    fireEvent.click(problems);
    expect(
      screen.getByRole("button", { name: "Checked at run time (Start)" }).className,
    ).toContain("channel-canvas-problems__item--warning");
  });

  it("keeps the control in the error tone when an error is present", async () => {
    await renderCanvas(
      [
        {
          code: "graph.empty",
          node_id: "nd_1",
          edge_id: null,
          path: [],
          detail: "Empty graph",
          severity: "error",
        },
        {
          code: "CHANNEL_TEMPLATE_TYPE_UNKNOWN",
          node_id: "nd_1",
          edge_id: null,
          path: [],
          detail: "Checked at run time",
          severity: "warning",
        },
      ],
      nodeGraph,
    );

    const problems = screen.getByRole("button", { name: "1 errors, 1 warnings" });
    expect(problems.className).not.toContain("channel-canvas-problems--warning");
    fireEvent.click(problems);
    expect(screen.getByRole("button", { name: "Empty graph (Start)" }).className).not.toContain(
      "channel-canvas-problems__item--warning",
    );
    expect(
      screen.getByRole("button", { name: "Checked at run time (Start)" }).className,
    ).toContain("channel-canvas-problems__item--warning");
  });

  it("keeps edit chrome while a run lock disables authoring", async () => {
    await renderCanvas([], nodeGraph, { appearance: "edit", mutable: false });

    expect(document.querySelector(".channel-canvas-stage--browse")).toBeNull();
    expect(document.querySelector(".react-flow__background")).not.toBeNull();
    const add = screen.getByRole("button", { name: "Add" });
    const undo = screen.getByRole("button", { name: "Undo" });
    const redo = screen.getByRole("button", { name: "Redo" });
    const run = document.querySelector(".channel-flow-node__run");
    if (!(run instanceof HTMLButtonElement)) throw new Error("missing run button");
    expect((add as HTMLButtonElement).disabled).toBe(true);
    expect((undo as HTMLButtonElement).disabled).toBe(true);
    expect((redo as HTMLButtonElement).disabled).toBe(true);
    expect(run.disabled).toBe(true);

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    const config = screen.getByRole("region", { name: "Configuration" });
    const configRun = within(config).getByRole("button", { name: "Run node" });
    expect((configRun as HTMLButtonElement).disabled).toBe(true);
  });

  it("opens configuration when a node is clicked during a session run", async () => {
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const sessionRun: ChannelRunDetail = {
      run: {
        job_id: "job_1",
        status: "running",
        outcome: null,
        target: "draft",
        version: null,
        draft_revision: 1,
        trigger_kind: "user",
        trigger_ref: "manual",
        trigger_node_id: "nd_1",
        trigger_actor_name: null,
        trigger_schedule_name: null,
        ignore_checkpoints: false,
        stop_at_node_id: "nd_1",
        failed_node_id: null,
        created_at: now,
        started_at: now,
        finished_at: null,
        error_code: null,
        error_message: null,
      },
      graph: nodeGraph,
      node_executions: [],
    };
    const onRun = vi.fn();
    await renderCanvas([], nodeGraph, { sessionRun, onRun });

    const run = document.querySelector(".channel-flow-node__run");
    if (!(run instanceof HTMLButtonElement)) throw new Error("missing run button");
    fireEvent.click(run);
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith("nd_1");
    expect(screen.queryByText("Waiting for this node")).toBeNull();

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    const header = document.querySelector(".channel-node-config__header");
    if (!(header instanceof HTMLElement)) throw new Error("missing header");
    expect(within(header).getByText("Manual")).toBeTruthy();
    expect(within(header).getByText("Start here")).toBeTruthy();
    const config = screen.getByRole("region", { name: "Configuration" });
    const result = screen.getByRole("region", { name: "This node's result" });
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();
    expect(screen.getByText("Waiting for this node")).toBeTruthy();
    expect(within(result).queryByRole("button")).toBeNull();

    fireEvent.click(within(config).getByRole("button", { name: "Run node" }));
    expect(onRun).toHaveBeenCalledTimes(2);
    expect(onRun).toHaveBeenLastCalledWith("nd_1");
  });
});
