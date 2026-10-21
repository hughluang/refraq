/** @vitest-environment jsdom */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const sessionPermissions = vi.hoisted(() => ({ current: [] as string[] }));

vi.mock("@/features/channels/api", () => ({
  getExecutionOutput: vi.fn(),
}));

const LABELS: Record<string, string> = {
  "channels.canvas.add": "Add",
  "channels.canvas.empty": "Add a trigger to start this channel.",
  "channels.canvas.connectNone": "This output cannot connect to another node.",
  "channels.canvas.nextStep": "Next step",
  "channels.canvas.permissionRequired": "Requires {{permission}}",
  "channels.node.permissionReadOnly":
    "This configuration is view only. Editing it requires {{permission}}.",
  "channels.node.name": "Name",
  "channels.config.fields.transform.code.code": "Code",
  "channels.config.fields.transform.code.timeout_sec": "Timeout (seconds)",
  "channels.canvas.undo": "Undo",
  "channels.canvas.redo": "Redo",
  "channels.canvas.toolbar": "Canvas tools",
  "channels.canvas.zoomIn": "Zoom in",
  "channels.canvas.zoomOut": "Zoom out",
  "channels.canvas.zoomPercent": "Zoom {{percent}}%",
  "channels.canvas.zoom100": "100%",
  "channels.canvas.fitView": "Fit view",
  "channels.canvas.minimap": "Minimap",
  "channels.canvas.shortcuts": "Keyboard shortcuts",
  "channels.canvas.shortcuts.group.edit": "Edit",
  "channels.canvas.shortcuts.group.view": "View",
  "channels.canvas.shortcuts.delete": "Delete selection",
  "channels.canvas.shortcuts.open": "Open settings",
  "channels.canvas.shortcuts.close": "Close the overlay, or clear the selection",
  "channels.canvas.shortcuts.help": "Show keyboard shortcuts",
  "channels.canvas.palette": "Nodes",
  "channels.canvas.problemsSummary": "{{errors}} errors, {{warnings}} warnings",
  "channels.node.run": "Run node",
  "channels.node.settings": "Settings",
  "channels.node.delete": "Delete",
  "channels.run.showFullOutput": "Show full output",
  "channels.run.outputFailed": "Output failed",
  "channels.editor.status.running": "Running",
  "channels.editor.status.succeeded": "Succeeded",
  "channels.editor.status.failed": "Failed",
  "channels.editor.status.skipped": "Skipped",
  "channels.editor.status.cancelled": "Cancelled",
  "channels.node.config": "Configuration",
  "channels.run.upstream": "Upstream outputs",
  "channels.run.result": "This node's result",
  "channels.run.noUpstream": "This node has no upstream nodes",
  "channels.run.idle": "Run the graph to see data here",
  "channels.run.absent": "This node has not executed yet",
  "channels.canvas.phase.waiting": "Waiting",
  "channels.run.notRun": "Not run",
  "channels.run.executions": "{{count}} executions",
  "channels.canvas.handle": "{{node}} {{port}} {{side}}",
  "channels.canvas.input": "input",
  "channels.canvas.output": "output",
  "channels.canvas.edge": "{{source}} to {{target}}",
  "channels.canvas.ports.main": "Main",
  "channels.canvas.ports.true": "True",
  "channels.canvas.ports.false": "False",
  "channels.canvas.ports.each": "Each",
  "channels.canvas.ports.done": "Done",
  "channels.canvas.ports.loop": "Loop",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const fallback = typeof options?.defaultValue === "string" ? options.defaultValue : key;
    const template = LABELS[key] ?? fallback;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  usePermissions: () => ({ data: sessionPermissions.current }),
}));

function stubDomApis() {
  sessionPermissions.current = [];
  localStorage.removeItem("refraq.channelCanvas.minimap");
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  // React Flow hides a node until ResizeObserver reports a size, and it only
  // draws an edge once both ends have measured handle bounds.
  class ResizeObserverStub {
    private readonly callback: ResizeObserverCallback;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }

    observe(target: Element) {
      queueMicrotask(() => {
        this.callback(
          [{ target, contentRect: target.getBoundingClientRect() } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
      });
    }

    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
  const layoutSize = (element: Element): { width: number; height: number } | null => {
    if (!(element instanceof HTMLElement)) return null;
    if (element.classList.contains("react-flow__node")) return { width: 160, height: 88 };
    if (element.classList.contains("react-flow__handle")) return { width: 8, height: 8 };
    return null;
  };
  for (const key of ["offsetWidth", "offsetHeight"] as const) {
    Object.defineProperty(HTMLElement.prototype, key, {
      configurable: true,
      get() {
        const box = layoutSize(this);
        return box ? box[key === "offsetWidth" ? "width" : "height"] : 0;
      },
    });
  }
  Document.prototype.elementFromPoint = () => null;
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
  const rect = () => ({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    bottom: 0,
    right: 0,
    width: 0,
    height: 0,
    toJSON() {
      return {};
    },
  });
  Range.prototype.getBoundingClientRect = rect;
  Range.prototype.getClientRects = () =>
    ({
      length: 0,
      item: () => null,
      [Symbol.iterator]: function* empty() {
        yield* [];
      },
    }) as unknown as () => DOMRectList;
  if (typeof window.DOMMatrixReadOnly === "undefined") {
    class DOMMatrixReadOnlyStub {
      m11 = 1;
      m12 = 0;
      m21 = 0;
      m22 = 1;
      m41 = 0;
      m42 = 0;

      constructor(init?: string) {
        const matrix = typeof init === "string" ? /matrix\(([^)]+)\)/.exec(init) : null;
        if (!matrix) return;
        const [a, b, c, d, e, f] = matrix[1].split(",").map((part) => Number(part.trim()));
        this.m11 = a || 1;
        this.m12 = b || 0;
        this.m21 = c || 0;
        this.m22 = d || 1;
        this.m41 = e || 0;
        this.m42 = f || 0;
      }
    }
    window.DOMMatrixReadOnly = DOMMatrixReadOnlyStub as unknown as typeof DOMMatrixReadOnly;
  }
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
  trigger: true,
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

const twoNodeGraph: Graph = {
  nodes: [
    nodeGraph.nodes[0]!,
    {
      id: "nd_2",
      ref: "manual_2",
      type: "manual",
      name: "Keep",
      position: { x: 280, y: 40 },
      config: {},
      on_error: "stop",
      retry: null,
    },
  ],
  edges: [],
  settings: nodeGraph.settings,
};

function openSettings(node: HTMLElement) {
  node.focus();
  fireEvent.keyDown(node, { key: "Enter" });
}

function renderCanvas(
  problems: GraphProblem[] = [],
  graph: Graph = EMPTY_GRAPH,
  options: {
    appearance?: "edit" | "browse";
    mutable?: boolean;
    sessionRun?: ChannelRunDetail | null;
    onRun?: (nodeId: string) => void;
    catalog?: NodeTypeSpec[];
    onChange?: (graph: Graph) => void;
    channelId?: string;
    colorScheme?: "light" | "dark";
  } = {},
) {
  const appearance = options.appearance ?? "edit";
  const mutable = options.mutable ?? appearance === "edit";
  return import("@/features/channels/ChannelCanvas").then(({ ChannelCanvas }) => {
    const element = (next: GraphProblem[]) =>
        createElement(
          MantineProvider,
          {
            env: "test",
            ...(options.colorScheme ? { forceColorScheme: options.colorScheme } : {}),
          },
          createElement(ChannelCanvas, {
          graph,
          catalog: options.catalog ?? [spec],
          appearance,
          mutable,
          problems: next,
          onChange: options.onChange ?? vi.fn(),
          sessionRun: options.sessionRun,
          onRun: options.onRun,
          channelId: options.channelId,
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

function mediaBlocks(css: string, query: string): string[] {
  const needle = `@media (${query})`;
  const blocks: string[] = [];
  let from = 0;
  while (from < css.length) {
    const start = css.indexOf(needle, from);
    if (start < 0) break;
    const open = css.indexOf("{", start);
    let depth = 0;
    let end = open;
    for (; end < css.length; end += 1) {
      const char = css[end];
      if (char === "{") depth += 1;
      else if (char === "}") {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    blocks.push(css.slice(open + 1, end));
    from = end + 1;
  }
  return blocks;
}

describe("ChannelCanvas controls", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("puts authoring, zoom, minimap, and shortcut help on the bottom toolbar", async () => {
    await renderCanvas();

    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    expect(document.querySelector(".channel-canvas-stage--browse")).toBeNull();
    expect(document.querySelector(".react-flow__controls")).toBeNull();
    expect(document.querySelector(".react-flow__controls-interactive")).toBeNull();
    expect(document.querySelector(".react-flow__background pattern")?.getAttribute("width")).toBe(
      "16",
    );

    const add = within(toolbar).getByRole("button", { name: "Add" });
    const undo = within(toolbar).getByRole("button", { name: "Undo" });
    const redo = within(toolbar).getByRole("button", { name: "Redo" });
    expect(add.querySelector("svg")).not.toBeNull();
    expect(within(toolbar).getByRole("button", { name: "Zoom out" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: /Zoom \d+%/ })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Zoom in" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Fit view" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Minimap" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Keyboard shortcuts" })).toBeTruthy();
    expect(toolbar.querySelectorAll("[role='separator']")).toHaveLength(3);
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

    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    expect(document.querySelector(".channel-canvas-stage--browse")).not.toBeNull();
    expect(document.querySelector(".react-flow__background")).toBeNull();
    expect(document.querySelector(".react-flow__handle")).not.toBeNull();
    expect(document.querySelector(".react-flow__controls-interactive")).toBeNull();
    expect(within(toolbar).getByRole("button", { name: "Zoom out" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: /Zoom \d+%/ })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Zoom in" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Fit view" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Minimap" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Keyboard shortcuts" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "1 errors, 0 warnings" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Redo" })).toBeNull();

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    expect(node.classList.contains("selected")).toBe(true);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    expect(document.querySelector(".react-flow__node-toolbar")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run node" })).toBeNull();
  });

  it("zooms from the percentage menu", async () => {
    await renderCanvas([], nodeGraph);
    window.matchMedia = (query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const viewport = document.querySelector(".react-flow__viewport");
    if (!(viewport instanceof HTMLElement)) throw new Error("missing viewport");
    const before = viewport.getAttribute("style");

    fireEvent.click(screen.getByRole("button", { name: /Zoom \d+%/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Zoom in" })).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: "Zoom out" })).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: "100%" })).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: "Fit view" })).toBeTruthy();
    fireEvent.click(within(menu).getByRole("menuitem", { name: "100%" }));

    await waitFor(() => {
      expect(viewport.getAttribute("style")).toContain("scale(1)");
      expect(viewport.getAttribute("style")).not.toBe(before);
    });
  });

  it("remembers the minimap and paints nodes with the family color", async () => {
    localStorage.removeItem("refraq.channelCanvas.minimap");
    await renderCanvas([], nodeGraph);
    expect(document.querySelector(".react-flow__minimap")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Minimap" }));
    expect(screen.getByRole("button", { name: "Minimap" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(localStorage.getItem("refraq.channelCanvas.minimap")).toBe("1");
    await waitFor(() => {
      const swatch = document.querySelector(".react-flow__minimap-node");
      if (!(swatch instanceof SVGElement)) throw new Error("missing minimap node");
      expect(swatch.style.fill).toBe("var(--mantine-color-orange-filled)");
    });

    cleanup();
    await renderCanvas([], nodeGraph);
    expect(document.querySelector(".react-flow__minimap")).not.toBeNull();
    localStorage.removeItem("refraq.channelCanvas.minimap");
  });

  it("opens shortcut help from ? and leaves viewport keys alone in a field", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    node.focus();
    fireEvent.keyDown(node, { key: "?" });
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeTruthy();
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
    });

    openSettings(node);
    const name = screen.getByRole("textbox", { name: "Name" });
    const zoom = new KeyboardEvent("keydown", {
      key: "0",
      code: "Digit0",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    const fit = new KeyboardEvent("keydown", {
      key: "!",
      code: "Digit1",
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    name.dispatchEvent(zoom);
    name.dispatchEvent(fit);
    expect(zoom.defaultPrevented).toBe(false);
    expect(fit.defaultPrevented).toBe(false);
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("undoes with ctrl+z and redoes with ctrl+y while the canvas is focused", async () => {
    await renderCanvas();
    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: /Manual/ }));
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    node.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "z",
        code: "KeyZ",
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
    await waitFor(() => {
      expect(document.querySelectorAll(".react-flow__node")).toHaveLength(0);
    });

    within(screen.getByRole("toolbar", { name: "Canvas tools" }))
      .getByRole("button", { name: "Add" })
      .dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "y",
          code: "KeyY",
          ctrlKey: true,
          bubbles: true,
          cancelable: true,
        }),
      );
    await waitFor(() => {
      expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);
    });
  });

  it("puts the problem control in the panel with a count badge", async () => {
    await renderCanvas([
      { code: "graph.empty", node_id: null, edge_id: null, path: [], detail: "Empty graph" },
    ]);

    const problems = screen.getByRole("button", { name: "1 errors, 0 warnings" });
    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    expect(toolbar.contains(problems)).toBe(true);
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
    expect((add as HTMLButtonElement).disabled).toBe(true);
    expect((undo as HTMLButtonElement).disabled).toBe(true);
    expect((redo as HTMLButtonElement).disabled).toBe(true);

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    const toolbar = document.querySelector(".react-flow__node-toolbar");
    if (!(toolbar instanceof HTMLElement)) throw new Error("missing node toolbar");
    const run = within(toolbar).getByRole("button", { name: "Run node" });
    const remove = within(toolbar).getByRole("button", { name: "Delete" });
    expect((run as HTMLButtonElement).disabled).toBe(true);
    expect((remove as HTMLButtonElement).disabled).toBe(true);
    expect(
      (within(toolbar).getByRole("button", { name: "Settings" }) as HTMLButtonElement).disabled,
    ).toBe(false);
    openSettings(node);
    const header = document.querySelector(".channel-node-config__header");
    if (!(header instanceof HTMLElement)) throw new Error("missing header");
    const configRun = within(header).getByRole("button", { name: "Run node" });
    expect((configRun as HTMLButtonElement).disabled).toBe(true);
    expect(
      within(screen.getByRole("region", { name: "Configuration" })).queryByRole("button", {
        name: "Run node",
      }),
    ).toBeNull();
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

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    const run = document.querySelector(".channel-flow-node__run");
    if (!(run instanceof HTMLButtonElement)) throw new Error("missing run button");
    fireEvent.click(run);
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith("nd_1");
    expect(screen.queryByText("This node has not executed yet")).toBeNull();

    openSettings(node);
    const header = document.querySelector(".channel-node-config__header");
    if (!(header instanceof HTMLElement)) throw new Error("missing header");
    expect(within(header).getByText("Manual")).toBeTruthy();
    expect(within(header).getByText("Start here")).toBeTruthy();
    const waiting = within(header).getByText("Waiting");
    expect(waiting.closest("[data-size]")?.getAttribute("data-size")).toBe("xs");
    expect(within(header).queryByText("This node has not executed yet")).toBeNull();
    const panel = header.closest(".channel-node-config");
    expect(panel?.className).toContain("channel-node-config--detail");
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Configuration" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "This node's result" })).toBeTruthy();
    expect(screen.getByText("This node has no upstream nodes")).toBeTruthy();
    expect(screen.getByText("This node has not executed yet")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show full output" })).toBeNull();

    fireEvent.click(within(header).getByRole("button", { name: "Run node" }));
    expect(onRun).toHaveBeenCalledTimes(2);
    expect(onRun).toHaveBeenLastCalledWith("nd_1");
  });

  it("uses the canvas phase label in the header and omits it without a run", async () => {
    await renderCanvas([], nodeGraph);
    const idleNode = document.querySelector(".react-flow__node");
    if (!(idleNode instanceof HTMLElement)) throw new Error("missing node");
    openSettings(idleNode);
    const idleHeader = document.querySelector(".channel-node-config__header");
    if (!(idleHeader instanceof HTMLElement)) throw new Error("missing header");
    expect(within(idleHeader).queryByText("Waiting")).toBeNull();
    expect(within(idleHeader).queryByText("Succeeded")).toBeNull();

    cleanup();
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const sessionRun: ChannelRunDetail = {
      run: {
        job_id: "job_1",
        status: "succeeded",
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
        finished_at: now,
        error_code: null,
        error_message: null,
      },
      graph: nodeGraph,
      node_executions: [
        {
          seq: 1,
          node_id: "nd_1",
          status: "succeeded",
          started_at: now,
          finished_at: now,
          output_bytes: 12,
          output_preview: { rows: ["hidden"] },
          output_truncated: false,
          error_code: null,
          error_message: null,
          error_detail: null,
        },
      ],
    };
    await renderCanvas([], nodeGraph, { sessionRun });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    const header = document.querySelector(".channel-node-config__header");
    if (!(header instanceof HTMLElement)) throw new Error("missing header");
    expect(within(header).getByText("Succeeded")).toBeTruthy();
    expect(screen.getByText(/hidden/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show input and output" })).toBeNull();
  });

  it("opens the three-column window for the focused node", async () => {
    await renderCanvas([], nodeGraph);

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Configuration" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "This node's result" })).toBeTruthy();
    expect(screen.getAllByText("This node has no upstream nodes")).toHaveLength(1);
    expect(screen.getAllByText("Run the graph to see data here")).toHaveLength(1);
    expect(
      within(screen.getByRole("region", { name: "Configuration" })).getByText(
        "channels.node.onError.stop",
      ),
    ).toBeTruthy();
    const panel = document.querySelector(".channel-node-config");
    expect(panel?.className).toContain("channel-node-config--detail");
    const header = document.querySelector(".channel-node-config__header");
    if (!(header instanceof HTMLElement)) throw new Error("missing header");
    expect(within(header).getByRole("button", { name: "Run node" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show input and output" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show parameters only" })).toBeNull();
  });

  it("keeps the same window when the node changes and after close", async () => {
    const pair: Graph = {
      nodes: [
        { ...nodeGraph.nodes[0]! },
        {
          id: "nd_2",
          ref: "next",
          type: "manual",
          name: "Next",
          position: { x: 280, y: 40 },
          config: {},
          on_error: "stop",
          retry: null,
        },
      ],
      edges: [],
      settings: nodeGraph.settings,
    };
    await renderCanvas([], pair);
    const nodes = [...document.querySelectorAll(".react-flow__node")];
    const first = nodes.find((item) => item.getAttribute("data-id") === "nd_1");
    const second = nodes.find((item) => item.getAttribute("data-id") === "nd_2");
    if (!(first instanceof HTMLElement) || !(second instanceof HTMLElement)) {
      throw new Error("missing nodes");
    }

    openSettings(first);
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();

    fireEvent.click(second);
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("Next");
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "channels.node.close" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Configuration" })).toBeNull();
    });

    openSettings(second);
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();
    expect(document.querySelector(".channel-node-config")?.className).toContain(
      "channel-node-config--detail",
    );
  });

  it("opens the same window after the open node is deleted", async () => {
    const pair: Graph = {
      nodes: [
        { ...nodeGraph.nodes[0]! },
        {
          id: "nd_2",
          ref: "next",
          type: "manual",
          name: "Next",
          position: { x: 280, y: 40 },
          config: {},
          on_error: "stop",
          retry: null,
        },
      ],
      edges: [],
      settings: nodeGraph.settings,
    };
    await renderCanvas([], pair);
    const first = document.querySelector('.react-flow__node[data-id="nd_1"]');
    const second = document.querySelector('.react-flow__node[data-id="nd_2"]');
    if (!(first instanceof HTMLElement) || !(second instanceof HTMLElement)) {
      throw new Error("missing nodes");
    }

    fireEvent.click(first);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();

    fireEvent.keyDown(document, { key: "Delete", code: "Delete" });
    await waitFor(() => {
      expect(document.querySelector('.react-flow__node[data-id="nd_1"]')).toBeNull();
    });

    openSettings(second);
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("Next");
    expect(screen.getByRole("region", { name: "Upstream outputs" })).toBeTruthy();
    expect(document.querySelector(".channel-node-config")?.className).toContain(
      "channel-node-config--detail",
    );
  });

  it("moves focus into the settings overlay and names it for the node", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);

    const panel = document.querySelector(".channel-node-config");
    if (!(panel instanceof HTMLElement)) throw new Error("missing panel");
    expect(panel.getAttribute("tabindex")).toBe("-1");
    expect(panel.getAttribute("role")).not.toBe("dialog");
    expect(panel.getAttribute("aria-modal")).toBeNull();
    expect(panel.getAttribute("aria-label")).toBe("Start");
    expect(panel === document.activeElement || panel.contains(document.activeElement)).toBe(true);
  });

  it("plays the leave motion when the canvas pane is clicked, then unmounts", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector('.react-flow__node[data-id="nd_1"]');
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");

    fireEvent.click(pane);
    expect(document.querySelector(".channel-node-config--leave")).not.toBeNull();
    expect(document.querySelector(".channel-node-config")).not.toBeNull();

    await waitFor(() => {
      expect(document.querySelector(".channel-node-config")).toBeNull();
    });
  });

  it("drops the overlay immediately for an edge selection and keeps that edge selected", async () => {
    const sink: NodeTypeSpec = {
      ...spec,
      type: "step",
      family: "transform",
      label: "Step",
      summary: "Next",
      trigger: false,
      inputs: [{ port: "in", description: "" }],
      outputs: [],
    };
    await renderCanvas(
      [],
      {
        nodes: [
          nodeGraph.nodes[0]!,
          {
            id: "nd_2",
            ref: "step",
            type: "step",
            name: "Next",
            position: { x: 280, y: 40 },
            config: {},
            on_error: "stop",
            retry: null,
          },
        ],
        edges: [
          {
            id: "ed_1",
            source: { node_id: "nd_1", port: "out" },
            target: { node_id: "nd_2", port: "in" },
          },
        ],
        settings: nodeGraph.settings,
      },
      { catalog: [spec, sink] },
    );
    const node = document.querySelector('.react-flow__node[data-id="nd_1"]');
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");
    fireEvent.click(pane);
    expect(document.querySelector(".channel-node-config--leave")).not.toBeNull();

    const edge = document.querySelector(".react-flow__edge[data-id='ed_1']");
    if (!(edge instanceof Element)) throw new Error("missing edge");
    fireEvent.click(edge);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    expect(edge.classList.contains("selected")).toBe(true);

    await act(() => new Promise((resolve) => setTimeout(resolve, 250)));
    expect(edge.classList.contains("selected")).toBe(true);
    expect(document.querySelector(".channel-node-config")).toBeNull();
  });

  it("closes the settings overlay on Escape and returns focus to that node", async () => {
    await renderCanvas([], twoNodeGraph);
    const closed = document.querySelector('.react-flow__node[data-id="nd_2"]');
    const other = document.querySelector('.react-flow__node[data-id="nd_1"]');
    if (!(closed instanceof HTMLElement) || !(other instanceof HTMLElement)) {
      throw new Error("missing node");
    }
    openSettings(closed);
    expect(document.querySelector(".channel-node-config")).not.toBeNull();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(document.querySelector(".channel-node-config")).toBeNull();
      expect(document.activeElement).toBe(closed);
    });
    expect(document.activeElement).not.toBe(other);
  });

  it("closes from the name field on Escape and keeps the typed name on the node", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector('.react-flow__node[data-id="nd_1"]');
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Renamed" },
    });
    expect(node.textContent).toContain("Renamed");

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "Escape" });
    await waitFor(() => {
      expect(document.querySelector(".channel-node-config")).toBeNull();
    });
    expect(node.textContent).toContain("Renamed");
    expect(document.activeElement).toBe(node);
  });

  it("leaves the settings overlay open when Escape was already handled", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    const name = screen.getByRole("textbox", { name: "Name" });
    name.addEventListener("keydown", (event) => {
      event.preventDefault();
    });

    fireEvent.keyDown(name, { key: "Escape" });
    expect(document.querySelector(".channel-node-config")).not.toBeNull();
    expect(document.querySelector(".channel-node-config--leave")).toBeNull();
  });

  it("drops the settings overlay immediately when reduced motion is requested", async () => {
    await renderCanvas([], twoNodeGraph);
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: query.includes("reduce"),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
    const closed = document.querySelector('.react-flow__node[data-id="nd_2"]');
    const other = document.querySelector('.react-flow__node[data-id="nd_1"]');
    if (!(closed instanceof HTMLElement) || !(other instanceof HTMLElement)) {
      throw new Error("missing node");
    }
    openSettings(closed);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector(".channel-node-config")).toBeNull();
    expect(document.activeElement).toBe(closed);
    expect(document.activeElement).not.toBe(other);
  });

  it("fades the shared overlay in and out and disables that motion when reduced", () => {
    const css = readFileSync(resolve(__dirname, "ChannelCanvas.css"), "utf8");
    const motion = mediaBlocks(css, "prefers-reduced-motion: no-preference").join("\n");
    expect(motion).toContain(".channel-node-config {");
    expect(motion).toContain(".channel-node-config--leave");
    expect(motion).toContain("var(--refraq-motion-base)");
    expect(motion).toContain("var(--refraq-ease-enter)");
    expect(motion).toContain("var(--refraq-ease-exit)");

    const frames = [
      ...motion.matchAll(/@keyframes (channel-node-config-(?:in|out)) \{([\s\S]*?)\n  \}/g),
    ];
    expect(frames.map((frame) => frame[1])).toEqual([
      "channel-node-config-in",
      "channel-node-config-out",
    ]);
    for (const frame of frames) {
      const body = frame[2] ?? "";
      expect(body).toMatch(/opacity:\s*0/);
      expect(body).not.toMatch(/\b(?:width|height|margin)\s*:/);
      const shifts = [...body.matchAll(/translateX\(([0-9.]+)px\)/g)].map((match) =>
        Number(match[1]),
      );
      expect(shifts.length).toBeGreaterThan(0);
      expect(Math.max(...shifts)).toBeLessThanOrEqual(8);
    }

    const reduced = mediaBlocks(css, "prefers-reduced-motion: reduce").join("\n");
    expect(reduced).toMatch(/\.channel-node-config[\s\S]*animation:\s*none/);

    const detailRule = css.match(/^\.channel-node-config--detail \{([\s\S]*?)\n\}/m)?.[1] ?? "";
    expect(detailRule).toBeTruthy();
    expect(detailRule).not.toMatch(/transition/);
  });

  it("states the node settings overlay motion constraints in the interaction doc", () => {
    const doc = readFileSync(
      resolve(__dirname, "../../../../docs/ui-console-interaction.md"),
      "utf8",
    );
    const section = doc.split(/^## 9\. /m)[0]?.split(/^## 8\. Motion/m)[1] ?? "";
    expect(section).toMatch(/node settings overlay may fade in and out/i);
    expect(section).toMatch(/does not shift layout/i);
    expect(section).not.toMatch(/focus altitude/i);
    expect(section).toMatch(/reduced-motion preference shows and hides the overlay immediately/i);
    expect(section).toMatch(/edge that enters the node currently running/i);
  });

  it("sizes the node window and keeps three columns", () => {
    const css = readFileSync(resolve(__dirname, "ChannelCanvas.css"), "utf8");
    expect(css).not.toMatch(/960px/);
    expect(css).not.toMatch(/@container/);

    const detail = css.match(/^\.channel-node-config--detail \{([\s\S]*?)\n\}/m)?.[1] ?? "";
    expect(css).toMatch(
      /--channel-canvas-controls-clearance:\s*calc\(15px \+ 1\.375rem \* var\(--mantine-scale\) \+ var\(--mantine-spacing-sm\)\)/,
    );
    expect(detail).toMatch(/width:\s*calc\(100% - 16px\)/);
    expect(detail).toMatch(
      /height:\s*calc\(100% - 8px - var\(--channel-canvas-controls-clearance\)\)/,
    );
    expect(detail).not.toMatch(/container-type/);

    const columns = css.match(/^\.channel-node-detail \{([\s\S]*?)\n\}/m)?.[1] ?? "";
    expect(columns).toMatch(
      /grid-template-columns:\s*minmax\(0, 1fr\) minmax\(0, 2fr\) minmax\(0, 1fr\)/,
    );
    expect(columns).not.toMatch(/240px|440px/);
    expect(css).not.toMatch(/channel-node-config--focus/);
  });
});

describe("empty canvas", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("shows the next step and adds a node from an empty canvas", async () => {
    await renderCanvas();

    expect(screen.getByText("Add a trigger to start this channel.")).toBeTruthy();
    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    const emptyAdd = screen
      .getAllByRole("button", { name: "Add" })
      .find((button) => !toolbar.contains(button));
    if (!(emptyAdd instanceof HTMLButtonElement)) throw new Error("missing empty-canvas add");
    fireEvent.click(emptyAdd);
    expect(screen.getByText("Nodes")).toBeTruthy();
    expect(screen.getByText("Manual")).toBeTruthy();
  });

  it("states the next step on an empty canvas without an add action while browsing", async () => {
    await renderCanvas([], EMPTY_GRAPH, { appearance: "browse", mutable: false });

    expect(screen.getByText("Add a trigger to start this channel.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
  });
});

describe("canvas color", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("follows the console color scheme", async () => {
    await renderCanvas([], nodeGraph, { colorScheme: "dark" });
    expect(document.querySelector(".react-flow")?.classList.contains("dark")).toBe(true);

    cleanup();
    await renderCanvas([], nodeGraph, { colorScheme: "light" });
    expect(document.querySelector(".react-flow")?.classList.contains("light")).toBe(true);
  });
});

function releaseOutput(name: string) {
  const handle = screen.getAllByRole("button", { hidden: true }).find(
    (element) => element.getAttribute("aria-label") === name,
  );
  if (!(handle instanceof HTMLElement)) throw new Error(`missing output ${name}`);
  const flow = document.querySelector(".react-flow");
  if (!(flow instanceof HTMLElement)) throw new Error("missing flow");
  Document.prototype.elementFromPoint = () => flow;
  fireEvent.mouseDown(handle, { button: 0, clientX: 8, clientY: 8 });
  fireEvent.mouseMove(document, { clientX: 48, clientY: 48 });
  fireEvent.mouseUp(document, { clientX: 48, clientY: 48 });
}

describe("unreachable output", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("explains a release when the output has no next node", async () => {
    await renderCanvas([], nodeGraph);
    await waitFor(() => {
      const node = document.querySelector(".react-flow__node");
      if (!(node instanceof HTMLElement) || node.style.visibility === "hidden") {
        throw new Error("node not measured");
      }
    });

    releaseOutput("Start out output");

    const note = screen.getByText("This output cannot connect to another node.");
    expect(note.getAttribute("aria-live")).toBe("polite");

    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");
    fireEvent.pointerDown(pane);
    expect(screen.queryByText("This output cannot connect to another node.")).toBeNull();
  });

  it("keeps the next-step choice when the output can still connect", async () => {
    await renderCanvas([], nodeGraph, { catalog: [spec, READ_SPEC] });
    await waitFor(() => {
      const node = document.querySelector(".react-flow__node");
      if (!(node instanceof HTMLElement) || node.style.visibility === "hidden") {
        throw new Error("node not measured");
      }
    });

    releaseOutput("Start out output");

    expect(screen.getByText("Next step")).toBeTruthy();
    expect(screen.queryByText("This output cannot connect to another node.")).toBeNull();
  });
});

describe("canvas selection", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("selects a node on click and shows its toolbar without opening settings", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.click(node);

    expect(node.classList.contains("selected")).toBe(true);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    const toolbar = document.querySelector(".react-flow__node-toolbar");
    if (!(toolbar instanceof HTMLElement)) throw new Error("missing node toolbar");
    expect(within(toolbar).getByRole("button", { name: "Settings" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Run node" })).toBeTruthy();
    expect(within(toolbar).getByRole("button", { name: "Delete" })).toBeTruthy();
  });

  it("opens settings from a double-click, Enter, or the toolbar settings button", async () => {
    await renderCanvas([], nodeGraph);
    const node = () => {
      const found = document.querySelector(".react-flow__node");
      if (!(found instanceof HTMLElement)) throw new Error("missing node");
      return found;
    };

    fireEvent.doubleClick(node());
    expect(document.querySelector(".channel-node-config")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "channels.node.close" }));
    await waitFor(() => {
      expect(document.querySelector(".channel-node-config")).toBeNull();
    });

    node().focus();
    fireEvent.keyDown(node(), { key: "Enter" });
    expect(document.querySelector(".channel-node-config")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "channels.node.close" }));
    await waitFor(() => {
      expect(document.querySelector(".channel-node-config")).toBeNull();
    });

    fireEvent.click(node());
    const toolbar = document.querySelector(".react-flow__node-toolbar");
    if (!(toolbar instanceof HTMLElement)) throw new Error("missing node toolbar");
    fireEvent.click(within(toolbar).getByRole("button", { name: "Settings" }));
    expect(document.querySelector(".channel-node-config")).not.toBeNull();
  });

  it("shift-clicks nodes into one selection that deletes and undoes together", async () => {
    await renderCanvas([], twoNodeGraph);
    const node = (id: string) => {
      const found = document.querySelector(`.react-flow__node[data-id="${id}"]`);
      if (!(found instanceof HTMLElement)) throw new Error(`missing ${id}`);
      return found;
    };

    fireEvent.click(node("nd_1"));
    fireEvent.keyDown(window, { key: "Shift", code: "ShiftLeft" });
    fireEvent.click(node("nd_2"), { shiftKey: true });

    expect(node("nd_1").classList.contains("selected")).toBe(true);
    expect(node("nd_2").classList.contains("selected")).toBe(true);
    expect(document.querySelector(".react-flow__node-toolbar")).toBeNull();
    expect(document.querySelector(".channel-node-config")).toBeNull();

    fireEvent.keyDown(document, { key: "Delete", code: "Delete" });
    await waitFor(() => {
      expect(document.querySelectorAll(".react-flow__node")).toHaveLength(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(document.querySelectorAll(".react-flow__node")).toHaveLength(2);
    });
  });

  it("box-selects while shift is held", async () => {
    await renderCanvas([], nodeGraph);
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");

    fireEvent.keyDown(window, { key: "Shift", code: "ShiftLeft" });
    fireEvent.pointerDown(pane, {
      button: 0,
      clientX: 12,
      clientY: 12,
      pointerId: 1,
      shiftKey: true,
      isPrimary: true,
    });
    fireEvent.pointerMove(pane, {
      clientX: 90,
      clientY: 90,
      pointerId: 1,
      shiftKey: true,
      isPrimary: true,
    });

    expect(pane.classList.contains("selection")).toBe(true);
    expect(document.querySelector(".react-flow__selection")).not.toBeNull();
  });

  it("keeps a plain click exclusive and lets shift add a node beside a selected edge", async () => {
    const sink: NodeTypeSpec = {
      ...spec,
      type: "step",
      family: "transform",
      label: "Step",
      summary: "Next",
      trigger: false,
      inputs: [{ port: "in", description: "" }],
      outputs: [],
    };
    await renderCanvas(
      [],
      {
        nodes: [
          nodeGraph.nodes[0]!,
          {
            id: "nd_2",
            ref: "step",
            type: "step",
            name: "Next",
            position: { x: 280, y: 40 },
            config: {},
            on_error: "stop",
            retry: null,
          },
        ],
        edges: [
          {
            id: "ed_1",
            source: { node_id: "nd_1", port: "out" },
            target: { node_id: "nd_2", port: "in" },
          },
        ],
        settings: nodeGraph.settings,
      },
      { catalog: [spec, sink] },
    );
    const edge = await waitFor(() => {
      const found = document.querySelector(".react-flow__edge[data-id='ed_1']");
      if (!(found instanceof Element)) throw new Error("missing edge");
      return found;
    });
    const node = document.querySelector('.react-flow__node[data-id="nd_2"]');
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.click(edge);
    expect(edge.classList.contains("selected")).toBe(true);
    fireEvent.click(node);
    expect(node.classList.contains("selected")).toBe(true);
    expect(edge.classList.contains("selected")).toBe(false);

    fireEvent.click(edge);
    expect(edge.classList.contains("selected")).toBe(true);
    expect(node.classList.contains("selected")).toBe(false);
    fireEvent.keyDown(window, { key: "Shift", code: "ShiftLeft" });
    fireEvent.click(node, { shiftKey: true });
    expect(node.classList.contains("selected")).toBe(true);
    expect(edge.classList.contains("selected")).toBe(true);
  });

  it("nudges the selection 8px, or 40px with shift, and merges presses within 500ms", async () => {
    await renderCanvas([], twoNodeGraph);
    const node = (id: string) => {
      const found = document.querySelector(`.react-flow__node[data-id="${id}"]`);
      if (!(found instanceof HTMLElement)) throw new Error(`missing ${id}`);
      return found;
    };
    const at = (id: string) => {
      const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(node(id).style.transform);
      if (!match) throw new Error(`missing transform for ${id}`);
      return { x: Number(match[1]), y: Number(match[2]) };
    };
    const start = at("nd_1");
    const other = at("nd_2");

    fireEvent.click(node("nd_1"));
    node("nd_1").focus();
    fireEvent.keyDown(node("nd_1"), { key: "ArrowRight" });
    fireEvent.keyDown(node("nd_1"), { key: "ArrowRight" });
    expect(at("nd_1")).toEqual({ x: start.x + 16, y: start.y });
    expect(at("nd_2")).toEqual(other);

    fireEvent.keyDown(node("nd_1"), { key: "ArrowDown", shiftKey: true });
    expect(at("nd_1")).toEqual({ x: start.x + 16, y: start.y + 40 });
    expect(at("nd_2")).toEqual(other);

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(at("nd_1")).toEqual(start);
    expect(at("nd_2")).toEqual(other);
    expect((screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(node("nd_1"));
    node("nd_1").focus();
    fireEvent.keyDown(node("nd_1"), { key: "ArrowRight" });
    await act(() => new Promise((resolve) => setTimeout(resolve, 520)));
    fireEvent.keyDown(node("nd_1"), { key: "ArrowRight" });
    await act(() => new Promise((resolve) => setTimeout(resolve, 520)));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(at("nd_1")).toEqual({ x: start.x + 8, y: start.y });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(at("nd_1")).toEqual(start);
  });

  it("drops a cancelled nudge and keeps redo until that burst commits", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    const at = () => {
      const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(node.style.transform);
      if (!match) throw new Error("missing transform");
      return { x: Number(match[1]), y: Number(match[2]) };
    };
    const undo = () => screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement;
    const redo = () => screen.getByRole("button", { name: "Redo" }) as HTMLButtonElement;
    const start = at();

    fireEvent.click(node);
    node.focus();
    fireEvent.keyDown(node, { key: "ArrowRight" });
    fireEvent.keyDown(node, { key: "ArrowLeft" });
    expect(at()).toEqual(start);
    expect(undo().disabled).toBe(true);
    expect(redo().disabled).toBe(true);

    fireEvent.keyDown(node, { key: "ArrowRight" });
    await act(() => new Promise((resolve) => setTimeout(resolve, 520)));
    fireEvent.click(undo());
    expect(at()).toEqual(start);
    expect(redo().disabled).toBe(false);

    fireEvent.click(node);
    node.focus();
    fireEvent.keyDown(node, { key: "ArrowRight" });
    expect(at()).toEqual({ x: start.x + 8, y: start.y });
    expect(redo().disabled).toBe(true);
    fireEvent.keyDown(node, { key: "z", code: "KeyZ", ctrlKey: true, shiftKey: true });
    expect(at()).toEqual({ x: start.x + 8, y: start.y });
    expect(redo().disabled).toBe(true);

    fireEvent.keyDown(node, { key: "ArrowLeft" });
    expect(at()).toEqual(start);
    expect(undo().disabled).toBe(true);
    expect(redo().disabled).toBe(false);
    fireEvent.click(redo());
    expect(at()).toEqual({ x: start.x + 8, y: start.y });
  });

  it("selects every node and edge from ctrl or cmd A and ignores that chord in a field", async () => {
    const sink: NodeTypeSpec = {
      ...spec,
      type: "step",
      family: "transform",
      label: "Step",
      summary: "Next",
      trigger: false,
      inputs: [{ port: "in", description: "" }],
      outputs: [],
    };
    await renderCanvas(
      [],
      {
        nodes: [
          nodeGraph.nodes[0]!,
          {
            id: "nd_2",
            ref: "step",
            type: "step",
            name: "Next",
            position: { x: 280, y: 40 },
            config: {},
            on_error: "stop",
            retry: null,
          },
        ],
        edges: [
          {
            id: "ed_1",
            source: { node_id: "nd_1", port: "out" },
            target: { node_id: "nd_2", port: "in" },
          },
        ],
        settings: nodeGraph.settings,
      },
      { catalog: [spec, sink] },
    );
    const node = (id: string) => {
      const found = document.querySelector(`.react-flow__node[data-id="${id}"]`);
      if (!(found instanceof HTMLElement)) throw new Error(`missing ${id}`);
      return found;
    };
    const edge = await waitFor(() => {
      const found = document.querySelector(".react-flow__edge[data-id='ed_1']");
      if (!(found instanceof Element)) throw new Error("missing edge");
      return found;
    });

    node("nd_1").focus();
    const selectAll = new KeyboardEvent("keydown", {
      key: "a",
      code: "KeyA",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      node("nd_1").dispatchEvent(selectAll);
    });
    expect(selectAll.defaultPrevented).toBe(true);
    expect(node("nd_1").classList.contains("selected")).toBe(true);
    expect(node("nd_2").classList.contains("selected")).toBe(true);
    expect(edge.classList.contains("selected")).toBe(true);
    expect(document.querySelector(".react-flow__node-toolbar")).toBeNull();
    expect(document.querySelector(".channel-node-config")).toBeNull();

    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");
    fireEvent.click(pane);
    fireEvent.click(node("nd_1"));
    openSettings(node("nd_1"));
    const name = screen.getByRole("textbox", { name: "Name" });
    const inField = new KeyboardEvent("keydown", {
      key: "a",
      code: "KeyA",
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      name.dispatchEvent(inField);
    });
    expect(inField.defaultPrevented).toBe(false);
  });

  it("clears the selection on Escape when no overlay is open", async () => {
    await renderCanvas([], twoNodeGraph);
    const node = (id: string) => {
      const found = document.querySelector(`.react-flow__node[data-id="${id}"]`);
      if (!(found instanceof HTMLElement)) throw new Error(`missing ${id}`);
      return found;
    };
    fireEvent.click(node("nd_1"));
    fireEvent.keyDown(window, { key: "Shift", code: "ShiftLeft" });
    fireEvent.click(node("nd_2"), { shiftKey: true });
    expect(node("nd_1").classList.contains("selected")).toBe(true);
    expect(node("nd_2").classList.contains("selected")).toBe(true);

    node("nd_1").focus();
    fireEvent.keyDown(node("nd_1"), { key: "Escape" });
    expect(node("nd_1").classList.contains("selected")).toBe(false);
    expect(node("nd_2").classList.contains("selected")).toBe(false);
  });

  it("does not nudge a locked graph or arrow keys inside settings", async () => {
    await renderCanvas([], nodeGraph, { appearance: "edit", mutable: false });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    const at = () => {
      const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(node.style.transform);
      if (!match) throw new Error("missing transform");
      return { x: Number(match[1]), y: Number(match[2]) };
    };
    const start = at();
    fireEvent.click(node);
    node.focus();
    fireEvent.keyDown(node, { key: "ArrowRight" });
    fireEvent.keyDown(node, { key: "ArrowDown", shiftKey: true });
    expect(at()).toEqual(start);

    cleanup();
    await renderCanvas([], nodeGraph);
    const editable = document.querySelector(".react-flow__node");
    if (!(editable instanceof HTMLElement)) throw new Error("missing node");
    const placed = () => {
      const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(editable.style.transform);
      if (!match) throw new Error("missing transform");
      return { x: Number(match[1]), y: Number(match[2]) };
    };
    const origin = placed();
    fireEvent.click(editable);
    openSettings(editable);
    const name = screen.getByRole("textbox", { name: "Name" });
    const arrow = new KeyboardEvent("keydown", {
      key: "ArrowRight",
      bubbles: true,
      cancelable: true,
    });
    name.dispatchEvent(arrow);
    expect(arrow.defaultPrevented).toBe(false);
    expect(placed()).toEqual(origin);
  });
});

describe("canvas control hints", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("shows the same name as the button after hovering for 200ms", async () => {
    await renderCanvas([], nodeGraph);
    vi.useFakeTimers();
    try {
      for (const name of ["Add", "Undo", "Redo"]) {
        const button = screen.getByRole("button", { name });
        fireEvent.mouseEnter(button);
        expect(screen.queryByRole("tooltip")).toBeNull();
        act(() => {
          vi.advanceTimersByTime(199);
        });
        expect(screen.queryByRole("tooltip")).toBeNull();
        act(() => {
          vi.advanceTimersByTime(1);
        });
        expect(screen.getByRole("tooltip").textContent).toBe(name);
        fireEvent.mouseLeave(button);
        act(() => {
          vi.advanceTimersByTime(0);
        });
      }
    } finally {
      vi.useRealTimers();
    }
  });
});

function catalogSpec(
  type: string,
  inputs: NodeTypeSpec["inputs"],
  outputs: NodeTypeSpec["outputs"],
  trigger = false,
): NodeTypeSpec {
  return {
    type,
    family: type.split(".")[0] ?? "transform",
    label: type,
    summary: type,
    description: "",
    trigger,
    inputs,
    outputs,
    config_schema: {},
    permission: null,
  };
}

function placed(
  id: string,
  type: string,
  name: string,
  x: number,
): Graph["nodes"][number] {
  return {
    id,
    ref: id,
    type,
    name,
    position: { x, y: 40 },
    config: {},
    on_error: "stop",
    retry: null,
  };
}

const IF_SPEC = catalogSpec("transform.if", [{ port: "main", description: "" }], [
  { port: "true", description: "", loop_back: false },
  { port: "false", description: "", loop_back: false },
]);
const FOR_SPEC = catalogSpec(
  "volume.for",
  [
    { port: "main", description: "" },
    { port: "loop", description: "" },
  ],
  [
    { port: "each", description: "", loop_back: true },
    { port: "done", description: "", loop_back: false },
  ],
);
const READ_SPEC = catalogSpec("read.sql", [{ port: "main", description: "" }], [
  { port: "main", description: "", loop_back: false },
]);
const MERGE_SPEC = catalogSpec("transform.merge", [{ port: "main", description: "" }], [
  { port: "main", description: "", loop_back: false },
]);

describe("channel ports", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  async function port(name: string) {
    return waitFor(() => screen.getByRole("button", { name }));
  }

  it("shows true and false outputs on If", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("check", "transform.if", "Check", 40)],
    }, { catalog: [IF_SPEC] });

    expect(await port("Check True output")).toBeTruthy();
    expect(await port("Check False output")).toBeTruthy();
    expect(screen.getByText("True")).toBeTruthy();
    expect(screen.getByText("False")).toBeTruthy();
    expect((await port("Check True output")).getAttribute("data-handleid")).toBe("true");
  });

  it("shows For inputs and the loop-back output", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("walk", "volume.for", "Walk", 40)],
    }, { catalog: [FOR_SPEC] });

    expect(await port("Walk Main input")).toBeTruthy();
    expect((await port("Walk Loop input")).getAttribute("data-handlepos")).toBe("bottom");
    const each = await port("Walk Each output");
    expect(each.className).toContain("channel-flow-handle--loop");
    expect(await port("Walk Done output")).toBeTruthy();
    expect(screen.getByText("Each")).toBeTruthy();
    expect(screen.getByText("Loop")).toBeTruthy();
  });

  it("keeps a non-main port when an edge is created, including through undo", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("check", "transform.if", "Check", 20), placed("read", "read.sql", "Read", 280)],
    }, { catalog: [IF_SPEC, READ_SPEC], onChange });

    fireEvent.click(await port("Check True output"));
    fireEvent.click(await port("Read Main input"));

    expect(await screen.findByRole("group", { name: "True to Main" })).toBeTruthy();
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.edges).toEqual([
      expect.objectContaining({
        source: { node_id: "check", port: "true" },
        target: { node_id: "read", port: "main" },
      }),
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(screen.queryByRole("group", { name: "True to Main" })).toBeNull();
    });
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect(await screen.findByRole("group", { name: "True to Main" })).toBeTruthy();
  });

  it("lets Merge accept two incoming edges", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        placed("left", "read.sql", "Left", 20),
        placed("right", "read.sql", "Right", 20),
        placed("merge", "transform.merge", "Merge", 280),
      ],
    }, { catalog: [READ_SPEC, MERGE_SPEC], onChange });

    fireEvent.click(await port("Left Main output"));
    fireEvent.click(await port("Merge Main input"));
    fireEvent.click(await port("Right Main output"));
    fireEvent.click(await port("Merge Main input"));

    expect(await screen.findAllByRole("group", { name: "Main to Main" })).toHaveLength(2);
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.edges.map((edge) => [edge.source.node_id, edge.target.port])).toEqual([
      ["left", "main"],
      ["right", "main"],
    ]);
  });

  it("marks a return into the loop input", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("walk", "volume.for", "Walk", 20), placed("step", "read.sql", "Step", 280)],
      edges: [
        {
          id: "back",
          source: { node_id: "step", port: "main" },
          target: { node_id: "walk", port: "loop" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC] });

    await waitFor(() => {
      expect(document.querySelector(".channel-flow-edge--return")).not.toBeNull();
    });
    expect(screen.getByRole("group", { name: "Main to Loop" })).toBeTruthy();
  });

  it("counts repeated executions and marks a node that did not run", async () => {
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const ran: Graph = {
      ...EMPTY_GRAPH,
      nodes: [
        placed("trigger", "trigger.manual", "Start", 20),
        placed("body", "read.sql", "Body", 200),
        placed("skip", "read.sql", "Skip", 380),
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
          target: { node_id: "skip", port: "main" },
        },
      ],
    };
    const sessionRun: ChannelRunDetail = {
      run: {
        job_id: "job_1",
        status: "succeeded",
        outcome: "completed",
        target: "draft",
        version: null,
        draft_revision: 1,
        trigger_kind: "user",
        trigger_ref: "trigger",
        trigger_node_id: "trigger",
        trigger_actor_name: null,
        trigger_schedule_name: null,
        ignore_checkpoints: false,
        stop_at_node_id: null,
        failed_node_id: null,
        created_at: now,
        started_at: now,
        finished_at: now,
        error_code: null,
        error_message: null,
      },
      graph: ran,
      node_executions: [
        {
          seq: 1,
          node_id: "trigger",
          status: "succeeded",
          started_at: now,
          finished_at: now,
          output_bytes: 2,
          output_preview: {},
          error_code: null,
          error_message: null,
          error_detail: null,
        },
        {
          seq: 2,
          node_id: "body",
          status: "succeeded",
          started_at: now,
          finished_at: now,
          output_bytes: 2,
          output_preview: { current: 0 },
          error_code: null,
          error_message: null,
          error_detail: null,
        },
        {
          seq: 3,
          node_id: "body",
          status: "succeeded",
          started_at: now,
          finished_at: now,
          output_bytes: 2,
          output_preview: { current: 1 },
          error_code: null,
          error_message: null,
          error_detail: null,
        },
      ],
    };
    await renderCanvas([], ran, {
      catalog: [
        catalogSpec(
          "trigger.manual",
          [],
          [{ port: "main", description: "" }],
          true,
        ),
        READ_SPEC,
      ],
      sessionRun,
      appearance: "browse",
      mutable: false,
    });

    const body = document.querySelector(".react-flow__node[data-id='body']");
    const skip = document.querySelector(".react-flow__node[data-id='skip']");
    expect(body?.textContent).toContain("2 executions");
    expect(body?.querySelector(".channel-flow-node--succeeded")).not.toBeNull();
    expect(phaseLabel(skip)).toBe("Not run");
    expect(skip?.textContent).not.toContain("Not run");
    expect(skip?.querySelector(".channel-flow-node--dead")).not.toBeNull();
  });

  it("says Running on a node whose execution is running", async () => {
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [placed("trigger", "trigger.manual", "Start", 20)],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: {
        run: {
          job_id: "job_1",
          status: "running",
          outcome: null,
          target: "draft",
          version: null,
          draft_revision: 1,
          trigger_kind: "user",
          trigger_ref: "trigger",
          trigger_node_id: "trigger",
          trigger_actor_name: null,
          trigger_schedule_name: null,
          ignore_checkpoints: false,
          stop_at_node_id: null,
          failed_node_id: null,
          created_at: now,
          started_at: now,
          finished_at: null,
          error_code: null,
          error_message: null,
        },
        graph,
        node_executions: [
          {
            seq: 1,
            node_id: "trigger",
            status: "running",
            started_at: now,
            finished_at: null,
            output_bytes: 0,
            output_preview: null,
            error_code: null,
            error_message: null,
            error_detail: null,
          },
        ],
      },
    });

    const node = document.querySelector(".react-flow__node[data-id='trigger']");
    expect(phaseLabel(node)).toBe("Running");
    expect(node?.textContent).not.toContain("Running");
  });

  it("says Waiting, not the detail-panel sentence, on a node that has not started", async () => {
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [
        placed("trigger", "trigger.manual", "Start", 20),
        placed("body", "read.sql", "Body", 200),
      ],
      edges: [
        {
          id: "e1",
          source: { node_id: "trigger", port: "main" },
          target: { node_id: "body", port: "main" },
        },
      ],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
        READ_SPEC,
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: {
        run: {
          job_id: "job_1",
          status: "running",
          outcome: null,
          target: "draft",
          version: null,
          draft_revision: 1,
          trigger_kind: "user",
          trigger_ref: "trigger",
          trigger_node_id: "trigger",
          trigger_actor_name: null,
          trigger_schedule_name: null,
          ignore_checkpoints: false,
          stop_at_node_id: null,
          failed_node_id: null,
          created_at: now,
          started_at: now,
          finished_at: null,
          error_code: null,
          error_message: null,
        },
        graph,
        node_executions: [
          {
            seq: 1,
            node_id: "trigger",
            status: "succeeded",
            started_at: now,
            finished_at: now,
            output_bytes: 0,
            output_preview: null,
            error_code: null,
            error_message: null,
            error_detail: null,
          },
        ],
      },
    });

    const body = document.querySelector(".react-flow__node[data-id='body']");
    expect(phaseLabel(body)).toBe("Waiting");
    expect(body?.textContent).not.toContain("Waiting");
  });

  it("says Failed on a node whose execution failed", async () => {
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [placed("trigger", "trigger.manual", "Start", 20)],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: {
        run: {
          job_id: "job_1",
          status: "failed",
          outcome: "failed",
          target: "draft",
          version: null,
          draft_revision: 1,
          trigger_kind: "user",
          trigger_ref: "trigger",
          trigger_node_id: "trigger",
          trigger_actor_name: null,
          trigger_schedule_name: null,
          ignore_checkpoints: false,
          stop_at_node_id: null,
          failed_node_id: "trigger",
          created_at: now,
          started_at: now,
          finished_at: now,
          error_code: "boom",
          error_message: "nope",
        },
        graph,
        node_executions: [
          {
            seq: 1,
            node_id: "trigger",
            status: "failed",
            started_at: now,
            finished_at: now,
            output_bytes: 0,
            output_preview: null,
            error_code: "boom",
            error_message: "nope",
            error_detail: null,
          },
        ],
      },
    });

    const node = document.querySelector(".react-flow__node[data-id='trigger']");
    expect(phaseLabel(node)).toBe("Failed");
    expect(node?.textContent).not.toContain("Failed");
  });

  it("keeps the selected class beside the running phase", async () => {
    const now = Instant.parse("2026-01-01T00:00:00Z");
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [placed("trigger", "trigger.manual", "Start", 20)],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: {
        run: {
          job_id: "job_1",
          status: "running",
          outcome: null,
          target: "draft",
          version: null,
          draft_revision: 1,
          trigger_kind: "user",
          trigger_ref: "trigger",
          trigger_node_id: "trigger",
          trigger_actor_name: null,
          trigger_schedule_name: null,
          ignore_checkpoints: false,
          stop_at_node_id: null,
          failed_node_id: null,
          created_at: now,
          started_at: now,
          finished_at: null,
          error_code: null,
          error_message: null,
        },
        graph,
        node_executions: [
          {
            seq: 1,
            node_id: "trigger",
            status: "running",
            started_at: now,
            finished_at: null,
            output_bytes: 0,
            output_preview: null,
            error_code: null,
            error_message: null,
            error_detail: null,
          },
        ],
      },
    });

    const shell = document.querySelector(".react-flow__node[data-id='trigger']");
    if (!(shell instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(shell);
    const card = shell.querySelector(".channel-flow-node");
    expect(card?.classList.contains("channel-flow-node--selected")).toBe(true);
    expect(card?.classList.contains("channel-flow-node--running")).toBe(true);
    expect(card?.classList.contains("channel-flow-node--problem")).toBe(false);
  });

  it("does not show a phase when the node has not run", async () => {
    await renderCanvas([], nodeGraph, { appearance: "browse", mutable: false });
    expect(document.querySelector(".channel-flow-node__status")).toBeNull();
  });
});

describe("channel node anatomy", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("draws a family-tinted icon tile beside the type and name", async () => {
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          placed("start", "trigger.manual", "Start", 20),
          placed("load", "read.sql", "Load customers", 280),
          placed("save", "write.entity", "Save", 540),
          placed("odd", "misc.thing", "Odd", 800),
        ],
      },
      {
        catalog: [
          catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
          READ_SPEC,
          catalogSpec("write.entity", [{ port: "main", description: "" }], []),
        ],
      },
    );

    const card = (id: string) =>
      document.querySelector(`.react-flow__node[data-id='${id}'] .channel-flow-node`);
    await waitFor(() => {
      expect(card("start")).not.toBeNull();
    });
    const tile = (id: string) => card(id)?.querySelector(".channel-flow-node__icon");
    expect(tile("start")?.classList.contains("channel-flow-node__icon--orange")).toBe(true);
    expect(tile("start")?.querySelector("svg")).not.toBeNull();
    expect(tile("load")?.classList.contains("channel-flow-node__icon--blue")).toBe(true);
    expect(tile("save")?.classList.contains("channel-flow-node__icon--grape")).toBe(true);
    expect(tile("odd")?.classList.contains("channel-flow-node__icon--gray")).toBe(true);
    const name = card("load")?.querySelector(".channel-flow-node__name");
    expect(name?.textContent).toBe("Load customers");
    expect(name?.getAttribute("title")).toBe("Load customers");
  });

  it("marks the edges of the one selected node as adjacent", async () => {
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          placed("start", "trigger.manual", "Start", 20),
          placed("body", "read.sql", "Body", 280),
          placed("next", "read.sql", "Next", 540),
        ],
        edges: [
          {
            id: "into",
            source: { node_id: "start", port: "main" },
            target: { node_id: "body", port: "main" },
          },
          {
            id: "beyond",
            source: { node_id: "body", port: "main" },
            target: { node_id: "next", port: "main" },
          },
        ],
      },
      {
        catalog: [
          catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
          READ_SPEC,
        ],
      },
    );

    const edge = (id: string) => document.querySelector(`.react-flow__edge[data-id='${id}']`);
    const adjacent = (id: string) => edge(id)?.classList.contains("channel-flow-edge--adjacent");
    const node = (id: string) => {
      const shell = document.querySelector(`.react-flow__node[data-id='${id}']`);
      if (!(shell instanceof HTMLElement)) throw new Error(`missing node ${id}`);
      return shell;
    };
    await waitFor(() => {
      expect(edge("beyond")).not.toBeNull();
    });
    expect(adjacent("into")).toBe(false);
    expect(adjacent("beyond")).toBe(false);

    fireEvent.click(node("body"));
    await waitFor(() => {
      expect(adjacent("into")).toBe(true);
    });
    expect(adjacent("beyond")).toBe(true);

    fireEvent.click(node("start"));
    await waitFor(() => {
      expect(adjacent("beyond")).toBe(false);
    });
    expect(adjacent("into")).toBe(true);
  });
});

function phaseLabel(node: Element | null | undefined): string | null {
  return node?.querySelector(".channel-flow-node__status")?.getAttribute("aria-label") ?? null;
}

describe("channel edges", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("draws an arrow whose paint follows the edge stroke", async () => {
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          placed("start", "trigger.manual", "Start", 20),
          placed("body", "read.sql", "Body", 280),
        ],
        edges: [
          {
            id: "e1",
            source: { node_id: "start", port: "main" },
            target: { node_id: "body", port: "main" },
          },
        ],
      },
      {
        catalog: [
          catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
          READ_SPEC,
        ],
      },
    );

    const edge = await screen.findByRole("group", { name: "Main to Main" });
    const path = edge.querySelector(".react-flow__edge-path");
    const markerEnd = path?.getAttribute("marker-end") ?? "";
    const markerId = /url\('#([^']+)'\)/.exec(markerEnd)?.[1] ?? "";
    const arrow = markerId
      ? document.getElementById(markerId)?.querySelector("polyline.arrowclosed")
      : null;
    expect(arrow).toBeTruthy();
    expect(arrow?.getAttribute("style") ?? "").not.toMatch(/#(?:555|b1b1b7)/i);
    expect((arrow as SVGElement).style.fill).toBe("context-stroke");
    expect((arrow as SVGElement).style.stroke).toBe("context-stroke");
  });

  it("marks the edge into a running node as live", async () => {
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [
        placed("start", "trigger.manual", "Start", 20),
        placed("body", "read.sql", "Body", 240),
        placed("next", "read.sql", "Next", 460),
      ],
      edges: [
        {
          id: "into",
          source: { node_id: "start", port: "main" },
          target: { node_id: "body", port: "main" },
        },
        {
          id: "beyond",
          source: { node_id: "body", port: "main" },
          target: { node_id: "next", port: "main" },
        },
      ],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
        READ_SPEC,
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: runDetail(graph, "running", [
        { seq: 1, node_id: "start", status: "succeeded" },
        { seq: 2, node_id: "body", status: "running" },
      ]),
    });

    const edge = (id: string) => document.querySelector(`.react-flow__edge[data-id='${id}']`);
    await waitFor(() => {
      expect(edge("into")).not.toBeNull();
    });
    expect(edge("into")?.classList.contains("channel-flow-edge--live")).toBe(true);
    expect(edge("beyond")?.classList.contains("channel-flow-edge--live")).toBe(false);
    expect(edge("beyond")?.classList.contains("channel-flow-edge--settled")).toBe(false);
  });

  it("fades an edge when its source or target did not run", async () => {
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [
        placed("start", "trigger.manual", "Start", 20),
        placed("body", "read.sql", "Body", 220),
        placed("skip", "read.sql", "Skip", 420),
        placed("after", "read.sql", "After", 620),
      ],
      edges: [
        {
          id: "walked",
          source: { node_id: "start", port: "main" },
          target: { node_id: "body", port: "main" },
        },
        {
          id: "into-skip",
          source: { node_id: "body", port: "main" },
          target: { node_id: "skip", port: "main" },
        },
        {
          id: "from-skip",
          source: { node_id: "skip", port: "main" },
          target: { node_id: "after", port: "main" },
        },
      ],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
        READ_SPEC,
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: runDetail(graph, "succeeded", [
        { seq: 1, node_id: "start", status: "succeeded" },
        { seq: 2, node_id: "body", status: "succeeded" },
      ]),
    });

    const edge = (id: string) => document.querySelector(`.react-flow__edge[data-id='${id}']`);
    await waitFor(() => {
      expect(edge("into-skip")).not.toBeNull();
    });
    expect(edge("walked")?.classList.contains("channel-flow-edge--settled")).toBe(false);
    expect(edge("into-skip")?.classList.contains("channel-flow-edge--settled")).toBe(true);
    expect(edge("from-skip")?.classList.contains("channel-flow-edge--settled")).toBe(true);
  });

  it("does not paint a failed execution as a failure edge", async () => {
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [
        placed("start", "trigger.manual", "Start", 20),
        placed("body", "read.sql", "Body", 280),
      ],
      edges: [
        {
          id: "e1",
          source: { node_id: "start", port: "main" },
          target: { node_id: "body", port: "main" },
        },
      ],
    };
    await renderCanvas([], graph, {
      catalog: [
        catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
        READ_SPEC,
      ],
      appearance: "browse",
      mutable: false,
      sessionRun: runDetail(graph, "failed", [
        { seq: 1, node_id: "start", status: "succeeded" },
        { seq: 2, node_id: "body", status: "failed" },
      ]),
    });

    const edge = () => document.querySelector(".react-flow__edge[data-id='e1']");
    await waitFor(() => {
      expect(edge()).not.toBeNull();
    });
    expect(edge()?.getAttribute("class") ?? "").not.toMatch(/fail/i);
    expect(edge()?.classList.contains("channel-flow-edge--live")).toBe(false);
    expect(edge()?.classList.contains("channel-flow-edge--settled")).toBe(false);
  });
});

function runDetail(
  graph: Graph,
  status: string,
  executions: { seq: number; node_id: string; status: string }[],
): ChannelRunDetail {
  const now = Instant.parse("2026-01-01T00:00:00Z");
  const terminal = status === "succeeded" || status === "failed" || status === "cancelled";
  return {
    run: {
      job_id: "job_1",
      status,
      outcome: terminal ? (status === "failed" ? "failed" : "completed") : null,
      target: "draft",
      version: null,
      draft_revision: 1,
      trigger_kind: "user",
      trigger_ref: "start",
      trigger_node_id: "start",
      trigger_actor_name: null,
      trigger_schedule_name: null,
      ignore_checkpoints: false,
      stop_at_node_id: null,
      failed_node_id: null,
      created_at: now,
      started_at: now,
      finished_at: terminal ? now : null,
      error_code: null,
      error_message: null,
    },
    graph,
    node_executions: executions.map((item) => ({
      seq: item.seq,
      node_id: item.node_id,
      status: item.status,
      started_at: now,
      finished_at: item.status === "running" ? null : now,
      output_bytes: 0,
      output_preview: null,
      output_truncated: false,
      error_code: null,
      error_message: null,
      error_detail: null,
    })),
  };
}

const CODE_SPEC: NodeTypeSpec = {
  ...catalogSpec(
    "transform.code",
    [{ port: "main", description: "" }],
    [{ port: "main", description: "" }],
  ),
  label: "Code",
  summary: "Runs Python",
  permission: "channel:code_write",
  config_schema: {
    type: "object",
    required: ["code"],
    properties: {
      code: {
        type: "string",
        description: "Body",
        contentMediaType: "text/x-python",
      },
      timeout_sec: {
        type: "integer",
        minimum: 1,
        maximum: 300,
        description: "Seconds",
      },
    },
  },
};

function codeGraph(): Graph {
  return {
    nodes: [
      {
        id: "nd_code",
        ref: "code",
        type: "transform.code",
        name: "Normalize",
        position: { x: 40, y: 40 },
        config: { code: "return 1" },
        on_error: "stop",
        retry: null,
      },
    ],
    edges: [],
    settings: EMPTY_GRAPH.settings,
  };
}

describe("guarded node authoring", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("does not add a guarded node when the session lacks its permission", async () => {
    await renderCanvas([], EMPTY_GRAPH, { catalog: [spec, CODE_SPEC] });
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "Canvas tools" })).getByRole("button", {
        name: "Add",
      }),
    );

    const guarded = screen.getByRole("button", { name: /Requires channel:code_write/ });
    expect(guarded.textContent).toContain("Code");
    expect((guarded as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(guarded);
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /Manual/ }));
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);
  });

  it("shows an existing guarded node read-only without the permission", async () => {
    await renderCanvas([], codeGraph(), { catalog: [CODE_SPEC] });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);

    const editor = await screen.findByRole("textbox", { name: "Code" });
    expect(editor.getAttribute("contenteditable")).toBe("false");
    expect(
      [...document.querySelectorAll(".cm-line")].map((line) => line.textContent),
    ).toEqual(["return 1"]);
    expect(screen.queryByRole("textbox", { name: "Timeout (seconds)" })).toBeNull();
    expect(
      screen.getByText("This configuration is view only. Editing it requires channel:code_write."),
    ).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Name" })).toBeTruthy();
  });

  it("lets the session edit a guarded node when it holds the permission", async () => {
    sessionPermissions.current = ["channel:code_write"];
    await renderCanvas([], codeGraph(), { catalog: [CODE_SPEC] });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);

    const editor = await screen.findByRole("textbox", { name: "Code" });
    expect(editor.getAttribute("contenteditable")).toBe("true");
    expect(screen.queryByText(/view only/i)).toBeNull();
    const timeout = screen.getByRole("textbox", { name: "Timeout (seconds)" });
    fireEvent.change(timeout, { target: { value: "45" } });
    expect((screen.getByRole("textbox", { name: "Timeout (seconds)" }) as HTMLInputElement).value).toBe(
      "45",
    );
  });
});

