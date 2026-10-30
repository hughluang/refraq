/** @vitest-environment jsdom */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listExecutions, nodeSample } from "@/features/channels/api";
import { CANVAS_PLUS_PATH } from "@/features/channels/CanvasPlusIcon";
import { EACH_INSET } from "@/features/channels/portLayout";
import {
  EMPTY_GRAPH,
  type ChannelRunDetail,
  type Graph,
  type NodeExecution,
  type GraphProblem,
  type NodeTypeSpec,
} from "@/features/channels/types";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { canvasViewportDuration } from "@/features/channels/useCanvasShortcuts";

function canvasPlus(root: ParentNode): SVGElement {
  const glyph = root.querySelector("svg.channel-canvas-plus");
  if (!(glyph instanceof SVGElement)) throw new Error("missing canvas plus");
  return glyph;
}

const sessionPermissions = vi.hoisted(() => ({ current: [] as string[] }));

vi.mock("@/features/channels/api", () => ({
  getExecutionOutput: vi.fn(),
  listExecutions: vi.fn(() => Promise.resolve({ items: [], total: 0, limit: 50, offset: 0 })),
  listDatasetRows: vi.fn(),
  listRounds: vi.fn(() => Promise.resolve({ items: [], total: 0, limit: 50, offset: 0 })),
  previewTemplate: vi.fn(),
  nodeSample: vi.fn(() =>
    Promise.resolve({
      scope: [],
      config_changed: false,
      upstream: [],
      node: {
        state: "not_recorded",
        seq: null,
        status: null,
        output: null,
        output_truncated: false,
        totals: {},
        input: null,
        input_totals: null,
        error: null,
      },
    }),
  ),
}));

const LABELS: Record<string, string> = {
  "channels.canvas.add": "Add",
  "channels.canvas.note": "Note",
  "channels.canvas.addNote": "Add a note",
  "channels.canvas.notePlaceholder": "Write a note",
  "channels.canvas.noteLabel": "Note",
  "channels.canvas.shortcuts.editNote": "Edit a note",
  "channels.canvas.empty": "Add a trigger to start this channel.",
  "channels.canvas.connectNone": "This output cannot connect to another node.",
  "channels.canvas.addRejected": "This node cannot be added here.",
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
  "channels.canvas.searchNodes": "Search nodes",
  "channels.canvas.searchEmpty": "No matching nodes",
  "channels.canvas.addFromPort": "Add the next step from {{port}}",
  "channels.canvas.insertNode": "Insert node",
  "channels.canvas.copy": "Copy",
  "channels.canvas.cut": "Cut",
  "channels.canvas.paste": "Paste",
  "channels.canvas.duplicate": "Duplicate",
  "channels.canvas.addHere": "Add a node here",
  "channels.canvas.runToNode": "Run to this node",
  "channels.canvas.skipTrigger":
    "Skipped {{count}} trigger nodes: a channel can have only one trigger",
  "channels.canvas.skipPermission": "Skipped {{count}} nodes that require {{permission}}",
  "channels.canvas.skipUnknown": "Skipped {{count}} nodes that are not in the catalog",
  "channels.canvas.clipboardFailed": "Could not write to the clipboard",
  "channels.canvas.pasteShortcut": "Use Ctrl+V or Cmd+V to paste",
  "channels.canvas.family.trigger": "Trigger",
  "channels.canvas.family.read": "Read",
  "channels.canvas.family.transform": "Transform",
  "channels.canvas.family.volume": "Volume",
  "channels.canvas.family.state": "State",
  "channels.canvas.family.write": "Write",
  "channels.canvas.family.action": "Outbound",
  "channels.canvas.shortcuts.addNode": "Add a node",
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
  container: null,
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
    vi.mocked(nodeSample).mockImplementation(() =>
      Promise.resolve({
        scope: [],
        config_changed: false,
        upstream: [],
        node: {
          state: "not_recorded",
          seq: null,
          status: null,
          output: null,
          output_truncated: false,
          totals: {},
          input: null,
          input_totals: null,
          error: null,
        },
      }),
    );
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
    expect(canvasPlus(add).getAttribute("viewBox")).toBe("0 0 14 14");
    expect(canvasPlus(add).querySelector("path")?.getAttribute("d")).toBe(CANVAS_PLUS_PATH);
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
    const search = screen.getByRole("textbox", { name: "Search nodes" });
    expect(document.activeElement).toBe(search);
    expect(screen.getByRole("option", { name: /Manual/ })).toBeTruthy();
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
    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));
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
    const now = "2026-01-01T00:00:00Z";
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
      node_summaries: [],
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
    const now = "2026-01-01T00:00:00Z";
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
      node_summaries: [
        { node_id: "nd_1", execution_count: 1, status_counts: { succeeded: 1 } },
      ],
    };
    vi.mocked(nodeSample).mockResolvedValue({
      scope: [],
      config_changed: false,
      upstream: [],
      node: {
        state: "ok",
        seq: 1,
        status: "succeeded",
        output: { note: "hidden" },
        output_truncated: false,
        totals: {},
        input: null,
        input_totals: null,
        error: null,
      },
    });
    vi.mocked(listExecutions).mockResolvedValue({
      items: [
        {
          seq: 1,
          node_id: "nd_1",
          status: "succeeded",
          output_preview: { rows: ["hidden"] },
          output_truncated: false,
          preview_only: false,
          preview_totals: {},
        } as NodeExecution,
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    await renderCanvas([], nodeGraph, { sessionRun, channelId: "chn_1" });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    const header = document.querySelector(".channel-node-config__header");
    if (!(header instanceof HTMLElement)) throw new Error("missing header");
    expect(within(header).getByText("Succeeded")).toBeTruthy();
    expect(await screen.findByText(/hidden/)).toBeTruthy();
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
    expect(section).toMatch(/The edge that enters the node currently running flows along its stroke/);
    expect(section).toMatch(/The running node's status icon rotates/);
    expect(section).toMatch(/its status icon appears once/);
    expect(section).toMatch(/A node or \*\*Channel Note\*\* created in this session fades in/);
    expect(section).toMatch(/An edge connected in this session draws along its stroke/);
    expect(section).toMatch(/Selection and hover change color at the fast duration/);
    expect(section).toMatch(/Viewport controls transition at the base duration/);
    expect(section).toMatch(/does not move layout/);
    expect(section).toMatch(
      /reduced-motion preference freezes every canvas motion and keeps the running edge in its running color/i,
    );
    expect(section).not.toMatch(/That edge is the only canvas motion/);
    expect(section).not.toMatch(/No other canvas glyph moves/);
    expect(section).not.toMatch(/The canvas still moves only the edge/);
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
    expect(screen.getByRole("textbox", { name: "Search nodes" })).toBeTruthy();
    expect(screen.getByRole("option", { name: /Manual/ })).toBeTruthy();
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

    expect(screen.getByRole("textbox", { name: "Search nodes" })).toBeTruthy();
    expect(document.querySelector(".channel-node-placeholder")).not.toBeNull();
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
    container: null,
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
  { port: "true", description: "" },
  { port: "false", description: "" },
]);
const FOR_SPEC = {
  ...catalogSpec(
    "volume.for",
    [
      { port: "main", description: "" },
      { port: "loop", description: "" },
    ],
    [
      { port: "each", description: "" },
      { port: "done", description: "" },
    ],
  ),
  container: { round_templates: [] },
};
const BATCH_SPEC = {
  ...catalogSpec(
    "volume.batch_read",
    [{ port: "main", description: "" }],
    [
      { port: "each", description: "" },
      { port: "done", description: "" },
    ],
  ),
  container: { round_templates: [] },
};
const READ_SPEC = catalogSpec("read.sql", [{ port: "main", description: "" }], [
  { port: "main", description: "" },
]);
const MERGE_SPEC = catalogSpec("transform.merge", [{ port: "main", description: "" }], [
  { port: "main", description: "" },
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

  it("draws For as a frame with each inset on the left facing right, and done on the right", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("walk", "volume.for", "Walk", 40)],
    }, { catalog: [FOR_SPEC] });

    const frame = document.querySelector('.react-flow__node[data-id="walk"]');
    if (!(frame instanceof HTMLElement)) throw new Error("missing frame");
    expect(frame.querySelector(".channel-flow-node--frame")).not.toBeNull();
    expect(frame.style.width).toBe("320px");
    expect(frame.style.height).toBe("180px");

    const main = await port("Walk Main input");
    expect(main.getAttribute("data-handlepos")).toBe("left");
    expect(main.style.left).toBe("");
    expect(screen.queryByRole("button", { name: "Walk Loop input" })).toBeNull();

    const each = await port("Walk Each output");
    expect(each.getAttribute("data-handlepos")).toBe("right");
    expect(each.className).toContain("channel-flow-handle--inset");
    expect(each.style.left).toBe("");
    expect(each.style.right).toBe("");
    expect(each.style.transform).toBe("");
    const done = await port("Walk Done output");
    expect(done.getAttribute("data-handlepos")).toBe("right");
    expect(done.className).not.toContain("channel-flow-handle--inset");
    expect(done.style.left).toBe("");
    expect(done.style.transform).toBe("");
    const css = readFileSync(resolve(__dirname, "ChannelCanvas.css"), "utf8");
    const insetHandle =
      css.match(
        /\.channel-flow-node \.react-flow__handle\.channel-flow-handle--inset \{([\s\S]*?)\n\}/,
      )?.[1] ?? "";
    expect(insetHandle).toContain(`left: ${EACH_INSET}px`);
    expect(insetHandle).toMatch(/right:\s*auto/);
    expect(insetHandle).toMatch(/transform:\s*translate\(-50%, -50%\)/);
    expect(screen.getByText("Each").className).toContain("channel-flow-port--inset");
    expect(screen.getByText("Done").className).toContain("channel-flow-port--right");

    const flow = frame.querySelector(".channel-flow-node");
    if (!(flow instanceof HTMLElement)) throw new Error("missing frame node");
    fireEvent.mouseEnter(flow);
    const eachAdd = screen.getByRole("button", { name: "Add the next step from Each" });
    const doneAdd = screen.getByRole("button", { name: "Add the next step from Done" });
    expect(eachAdd.classList.contains("channel-flow-port-add--outside")).toBe(false);
    expect(doneAdd.classList.contains("channel-flow-port-add--outside")).toBe(true);
    expect(canvasPlus(eachAdd).getAttribute("viewBox")).toBe("0 0 14 14");
    expect(canvasPlus(eachAdd).querySelector("path")?.getAttribute("d")).toBe(CANVAS_PLUS_PATH);
    expect(canvasPlus(doneAdd).getAttribute("viewBox")).toBe("0 0 14 14");
    expect(canvasPlus(doneAdd).querySelector("path")?.getAttribute("d")).toBe(CANVAS_PLUS_PATH);
  });

  it("draws Batch Read with the same frame, each, and done placement as For", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("batch", "volume.batch_read", "Batches", 40)],
    }, { catalog: [BATCH_SPEC] });

    const frame = document.querySelector('.react-flow__node[data-id="batch"]');
    if (!(frame instanceof HTMLElement)) throw new Error("missing frame");
    expect(frame.querySelector(".channel-flow-node--frame")).not.toBeNull();
    expect(frame.style.width).toBe("320px");
    expect(frame.style.height).toBe("180px");
    const each = await port("Batches Each output");
    expect(each.className).toContain("channel-flow-handle--inset");
    const done = await port("Batches Done output");
    expect(done.className).not.toContain("channel-flow-handle--inset");
    expect(done.getAttribute("data-handlepos")).toBe("right");
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

  it("stays up when an edge targets the removed loop port", async () => {
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

    expect(await screen.findByRole("button", { name: "Walk Main input" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Step Main output" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Walk Loop input" })).toBeNull();
    expect(document.querySelector(".channel-flow-edge--return")).toBeNull();
  });

  function flowNode(id: string) {
    const found = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    if (!(found instanceof HTMLElement)) throw new Error(`missing ${id}`);
    return found;
  }

  function translationOf(id: string) {
    const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(flowNode(id).style.transform);
    if (!match) throw new Error(`missing transform for ${id}`);
    return { x: Number(match[1]), y: Number(match[2]) };
  }

  function clientFor(flow: { x: number; y: number }) {
    const viewport = document.querySelector(".react-flow__viewport");
    if (!(viewport instanceof HTMLElement)) throw new Error("missing viewport");
    const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\) scale\(([-\d.]+)\)/.exec(
      viewport.style.transform,
    );
    if (!match) throw new Error(`viewport ${viewport.style.transform}`);
    const pane = document.querySelector(".react-flow");
    const rect = pane instanceof HTMLElement ? pane.getBoundingClientRect() : { left: 0, top: 0 };
    const zoom = Number(match[3]);
    return {
      x: flow.x * zoom + Number(match[1]) + rect.left,
      y: flow.y * zoom + Number(match[2]) + rect.top,
    };
  }

  function pointer(type: string, target: EventTarget, client: { x: number; y: number }) {
    const event = new MouseEvent(type, {
      button: 0,
      clientX: client.x,
      clientY: client.y,
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(event, "view", { value: window });
    target.dispatchEvent(event);
  }

  function dragNode(id: string, points: { x: number; y: number }[]) {
    const node = flowNode(id);
    const [start, ...rest] = points;
    if (!start) throw new Error("missing drag start");
    act(() => {
      pointer("mousedown", node, clientFor(start));
      for (const point of rest) pointer("mousemove", window, clientFor(point));
      pointer("mouseup", window, clientFor(rest.at(-1) ?? start));
    });
  }

  async function measured(id: string) {
    await waitFor(() => {
      if (flowNode(id).style.visibility === "hidden") throw new Error(`${id} not measured`);
    });
  }

  function releaseOutputAt(name: string, flow: { x: number; y: number }) {
    const handle = screen.getAllByRole("button", { hidden: true }).find(
      (element) => element.getAttribute("aria-label") === name,
    );
    if (!(handle instanceof HTMLElement)) throw new Error(`missing output ${name}`);
    const pane = document.querySelector(".react-flow");
    if (!(pane instanceof HTMLElement)) throw new Error("missing flow");
    Document.prototype.elementFromPoint = () => pane;
    const client = clientFor(flow);
    fireEvent.mouseDown(handle, { button: 0, clientX: client.x, clientY: client.y });
    fireEvent.mouseMove(document, { clientX: client.x + 24, clientY: client.y });
    fireEvent.mouseUp(document, { clientX: client.x, clientY: client.y });
  }

  it("stamps a late catalog onto a moved For and keeps that position", async () => {
    const { ChannelCanvas } = await import("@/features/channels/ChannelCanvas");
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [{ ...placed("walk", "volume.for", "Walk", 0), position: { x: 80, y: 80 } }],
    };
    const element = (catalog: NodeTypeSpec[]) =>
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ChannelCanvas, {
          graph,
          catalog,
          appearance: "edit",
          mutable: true,
          problems: [],
          onChange: vi.fn(),
        }),
      );
    const view = render(element([{ ...FOR_SPEC, container: null }]));
    await measured("walk");
    expect(flowNode("walk").querySelector(".channel-flow-node--frame")).toBeNull();
    dragNode("walk", [
      { x: 80, y: 80 },
      { x: 120, y: 80 },
      { x: 240, y: 160 },
    ]);
    const moved = translationOf("walk");
    expect(moved).not.toEqual({ x: 80, y: 80 });
    view.rerender(element([FOR_SPEC]));
    await waitFor(() => {
      expect(flowNode("walk").querySelector(".channel-flow-node--frame")).not.toBeNull();
    });
    expect(translationOf("walk")).toEqual(moved);
  });

  it("keeps a body's parent and relative position when the body is nudged", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("step", "read.sql", "Step", 0), position: { x: 80, y: 100 }, parent: "walk" },
        placed("walk", "volume.for", "Walk", 100),
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });

    const frame = flowNode("walk");
    expect(frame.classList.contains("parent")).toBe(true);
    expect(frame.style.width).toBe("336px");
    expect(frame.style.height).toBe("204px");
    expect(translationOf("step")).toEqual({ x: 180, y: 140 });

    fireEvent.click(flowNode("step"));
    flowNode("step").focus();
    fireEvent.keyDown(flowNode("step"), { key: "ArrowRight" });
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.nodes.find((item) => item.id === "step")).toMatchObject({
      parent: "walk",
      position: { x: 88, y: 100 },
    });
    const walk = saved.nodes.find((item) => item.id === "walk");
    expect(walk).not.toHaveProperty("parent");
    expect(walk).not.toHaveProperty("width");
    expect(walk).not.toHaveProperty("height");
  });

  it("draws a nested For inside the outer frame", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("step", "read.sql", "Step", 0), position: { x: 200, y: 200 }, parent: "inner" },
        {
          ...placed("inner", "volume.for", "Inner", 0),
          position: { x: 40, y: 48 },
          parent: "outer",
        },
        { ...placed("outer", "volume.for", "Outer", 0), position: { x: 10, y: 20 } },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC] });

    const outer = flowNode("outer");
    const inner = flowNode("inner");
    expect(outer.classList.contains("parent")).toBe(true);
    expect(inner.classList.contains("parent")).toBe(true);
    expect(inner.querySelector(".channel-flow-node--frame")).not.toBeNull();
    expect(outer.style.width).toBe("544px");
    expect(outer.style.height).toBe("400px");
    expect(inner.style.width).toBe("456px");
    expect(inner.style.height).toBe("304px");
    expect(translationOf("inner")).toEqual({ x: 50, y: 68 });
    expect(translationOf("step")).toEqual({ x: 250, y: 268 });
  });

  it("drops the each edge when a child leaves the frame and restores it on undo", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("walk", "volume.for", "Walk", 80), position: { x: 80, y: 80 } },
        { ...placed("step", "read.sql", "Step", 0), position: { x: 48, y: 48 }, parent: "walk" },
      ],
      edges: [
        {
          id: "each",
          source: { node_id: "walk", port: "each" },
          target: { node_id: "step", port: "main" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });
    await measured("step");

    dragNode("step", [
      { x: 128, y: 128 },
      { x: 160, y: 128 },
      { x: 520, y: 360 },
    ]);

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.nodes.find((item) => item.id === "step")).not.toHaveProperty("parent");
      expect(saved.edges).toEqual([]);
    });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const restored = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(restored.nodes.find((item) => item.id === "step")).toMatchObject({
        parent: "walk",
        position: { x: 48, y: 48 },
      });
      expect(restored.edges.map((item) => item.id)).toEqual(["each"]);
    });
  });

  it("drops the done edge when a node enters the frame", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("walk", "volume.for", "Walk", 80), position: { x: 80, y: 80 } },
        { ...placed("step", "read.sql", "Step", 520), position: { x: 520, y: 360 } },
      ],
      edges: [
        {
          id: "done",
          source: { node_id: "walk", port: "done" },
          target: { node_id: "step", port: "main" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });
    await measured("step");

    dragNode("step", [
      { x: 520, y: 360 },
      { x: 480, y: 320 },
      { x: 120, y: 120 },
    ]);

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      const step = saved.nodes.find((item) => item.id === "step");
      expect(step?.parent).toBe("walk");
      expect(saved.edges).toEqual([]);
    });
  });

  function dragThrough(
    id: string,
    points: { x: number; y: number }[],
    visit: (index: number) => void,
  ) {
    const node = flowNode(id);
    const [start, ...rest] = points;
    const [first, ...later] = rest;
    if (!start || !first) throw new Error("missing drag points");
    // The pointer leads the node by this much: the opening move only starts the gesture.
    const shift = 40;
    const lead = (point: { x: number; y: number }) => clientFor({ x: point.x + shift, y: point.y });
    act(() => {
      pointer("mousedown", node, clientFor(start));
      pointer("mousemove", window, lead(start));
      pointer("mousemove", window, lead(first));
    });
    try {
      visit(0);
      later.forEach((point, index) => {
        act(() => {
          pointer("mousemove", window, lead(point));
        });
        visit(index + 1);
      });
    } finally {
      act(() => {
        pointer("mouseup", window, lead(rest.at(-1) ?? start));
      });
    }
  }

  it("keeps a child that sits in the grown frame, and the frame keeps hugging it", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("walk", "volume.for", "Walk", 0), position: { x: 0, y: 0 } },
        { ...placed("step", "read.sql", "Step", 0), position: { x: 200, y: 40 }, parent: "walk" },
      ],
      edges: [
        {
          id: "each",
          source: { node_id: "walk", port: "each" },
          target: { node_id: "step", port: "main" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });
    await measured("step");
    expect(flowNode("walk").style.width).toBe("456px");

    dragThrough("step", [
      { x: 200, y: 40 },
      { x: 216, y: 40 },
    ], () => {
      expect(translationOf("step")).toEqual({ x: 216, y: 40 });
      expect(flowNode("walk").style.width).toBe("472px");
      expect(screen.getByRole("group", { name: "Each to Main" })).toBeTruthy();
    });

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.nodes.find((item) => item.id === "step")).toMatchObject({
        parent: "walk",
        position: { x: 216, y: 40 },
      });
      expect(saved.edges.map((item) => item.id)).toEqual(["each"]);
    });
  });

  it("previews leaving and restores the each edge when the center comes back", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("walk", "volume.for", "Walk", 0), position: { x: 0, y: 0 } },
        { ...placed("step", "read.sql", "Step", 0), position: { x: 48, y: 48 }, parent: "walk" },
      ],
      edges: [
        {
          id: "each",
          source: { node_id: "walk", port: "each" },
          target: { node_id: "step", port: "main" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });
    await measured("step");

    dragThrough("step", [
      { x: 48, y: 48 },
      { x: 400, y: 40 },
      { x: 48, y: 48 },
    ], (index) => {
      if (index === 0) {
        expect(flowNode("walk").style.width).toBe("320px");
        expect(flowNode("walk").style.height).toBe("180px");
        expect(screen.queryByRole("group", { name: "Each to Main" })).toBeNull();
        return;
      }
      expect(screen.getByRole("group", { name: "Each to Main" })).toBeTruthy();
    });

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.nodes.find((item) => item.id === "step")).toMatchObject({
        parent: "walk",
        position: { x: 48, y: 48 },
      });
      expect(saved.edges.map((item) => item.id)).toEqual(["each"]);
    });
  });

  it("does not adopt a card whose center stays outside the frame", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("walk", "volume.for", "Walk", 0), position: { x: 0, y: 0 } },
        { ...placed("step", "read.sql", "Step", 0), position: { x: 220, y: 40 } },
      ],
      edges: [
        {
          id: "done",
          source: { node_id: "walk", port: "done" },
          target: { node_id: "step", port: "main" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });
    await measured("step");

    dragThrough("step", [
      { x: 220, y: 40 },
      { x: 230, y: 40 },
    ], () => {
      expect(flowNode("walk").style.width).toBe("320px");
      expect(flowNode("walk").style.height).toBe("180px");
      expect(screen.getByRole("group", { name: "Done to Main" })).toBeTruthy();
    });

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.nodes.find((item) => item.id === "step")).not.toHaveProperty("parent");
      expect(saved.edges.map((item) => item.id)).toEqual(["done"]);
    });
    expect(flowNode("walk").style.width).toBe("320px");
  });

  it("grows the frame while a card's center is inside, then parents it on release", async () => {
    const onChange = vi.fn();
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [
        { ...placed("walk", "volume.for", "Walk", 0), position: { x: 80, y: 80 } },
        { ...placed("step", "read.sql", "Step", 0), position: { x: 300, y: 100 } },
      ],
      edges: [
        {
          id: "done",
          source: { node_id: "walk", port: "done" },
          target: { node_id: "step", port: "main" },
        },
      ],
    }, { catalog: [FOR_SPEC, READ_SPEC], onChange });
    await measured("step");

    dragThrough("step", [
      { x: 300, y: 100 },
      { x: 270, y: 100 },
    ], () => {
      expect(Number.parseFloat(flowNode("walk").style.width)).toBeGreaterThan(320);
      expect(screen.queryByRole("group", { name: "Done to Main" })).toBeNull();
    });

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.nodes.find((item) => item.id === "step")?.parent).toBe("walk");
      expect(saved.edges).toEqual([]);
    });
    expect(Number.parseFloat(flowNode("walk").style.width)).toBeGreaterThan(320);
  });

  it("parents a node created from each inside the frame", async () => {
    const onChange = vi.fn();
    const sql = { ...READ_SPEC, label: "SQL", summary: "Query rows" };
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [{ ...placed("walk", "volume.for", "Walk", 0), position: { x: 40, y: 40 } }],
      },
      { catalog: [FOR_SPEC, sql], onChange },
    );
    await measured("walk");

    releaseOutputAt("Walk Each output", { x: 80, y: 80 });
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "walk");
    expect(created?.parent).toBe("walk");
    expect(created?.position.x).toBeGreaterThanOrEqual(0);
    expect(created?.position.y).toBeGreaterThanOrEqual(0);
    expect(created!.position.x + 208).toBeLessThanOrEqual(320);
    expect(created!.position.y + 56).toBeLessThanOrEqual(180);
    expect(saved.edges).toEqual([
      expect.objectContaining({
        source: { node_id: "walk", port: "each" },
        target: { node_id: created?.id, port: "main" },
      }),
    ]);
  });

  it("keeps a done drop that is already outside the frame", async () => {
    const onChange = vi.fn();
    const sql = { ...READ_SPEC, label: "SQL", summary: "Query rows" };
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [{ ...placed("walk", "volume.for", "Walk", 0), position: { x: 40, y: 40 } }],
      },
      { catalog: [FOR_SPEC, sql], onChange },
    );
    await measured("walk");

    releaseOutputAt("Walk Done output", { x: 472, y: 32 });
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "walk");
    expect(created).not.toHaveProperty("parent");
    expect(created?.position).toEqual({ x: 480, y: 40 });
  });

  it("names the done port in Chinese and drops the loop port label", () => {
    const zhMessages = zh as Record<string, string>;
    const enMessages = en as Record<string, string>;
    expect(zhMessages["channels.canvas.ports.done"]).toBe("\u5b8c\u6210");
    expect(enMessages["channels.canvas.ports.done"]).toBe("Done");
    expect(zhMessages).not.toHaveProperty("channels.canvas.ports.loop");
    expect(enMessages).not.toHaveProperty("channels.canvas.ports.loop");
  });

  it("counts repeated executions and marks a node that did not run", async () => {
    const now = "2026-01-01T00:00:00Z";
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
      node_summaries: [
        { node_id: "trigger", execution_count: 1, status_counts: { succeeded: 1 } },
        { node_id: "body", execution_count: 2, status_counts: { succeeded: 2 } },
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
    const now = "2026-01-01T00:00:00Z";
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
        node_summaries: [
          { node_id: "trigger", execution_count: 1, status_counts: { running: 1 } },
        ],
      },
    });

    const node = document.querySelector(".react-flow__node[data-id='trigger']");
    expect(phaseLabel(node)).toBe("Running");
    expect(node?.textContent).not.toContain("Running");
  });

  it("says Waiting, not the detail-panel sentence, on a node that has not started", async () => {
    const now = "2026-01-01T00:00:00Z";
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
        node_summaries: [
          { node_id: "trigger", execution_count: 1, status_counts: { succeeded: 1 } },
        ],
      },
    });

    const body = document.querySelector(".react-flow__node[data-id='body']");
    expect(phaseLabel(body)).toBe("Waiting");
    expect(body?.textContent).not.toContain("Waiting");
  });

  it("says Failed on a node whose execution failed", async () => {
    const now = "2026-01-01T00:00:00Z";
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
        node_summaries: [
          { node_id: "trigger", execution_count: 1, status_counts: { failed: 1 } },
        ],
      },
    });

    const node = document.querySelector(".react-flow__node[data-id='trigger']");
    expect(phaseLabel(node)).toBe("Failed");
    expect(node?.textContent).not.toContain("Failed");
  });

  it("keeps the selected class beside the running phase", async () => {
    const now = "2026-01-01T00:00:00Z";
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
        node_summaries: [
          { node_id: "trigger", execution_count: 1, status_counts: { running: 1 } },
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

  it("asks for the latest execution only when statuses are mixed", async () => {
    vi.mocked(listExecutions).mockClear();
    vi.mocked(listExecutions).mockResolvedValue({
      items: [
        {
          seq: 3,
          node_id: "trigger",
          status: "failed",
          output_preview: null,
          output_truncated: false,
          preview_only: false,
          preview_totals: {},
        } as NodeExecution,
      ],
      total: 3,
      limit: 1,
      offset: 2,
    });
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [placed("trigger", "trigger.manual", "Start", 20)],
    };
    await renderCanvas([], graph, {
      catalog: [catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true)],
      appearance: "browse",
      mutable: false,
      channelId: "chn_1",
      sessionRun: runDetail(graph, "failed", [
        { seq: 1, node_id: "trigger", status: "succeeded" },
        { seq: 2, node_id: "trigger", status: "succeeded" },
        { seq: 3, node_id: "trigger", status: "failed" },
      ]),
    });
    await waitFor(() => {
      expect(listExecutions).toHaveBeenCalledWith("chn_1", "job_1", {
        node_id: "trigger",
        limit: 1,
        offset: 2,
      });
    });
    expect(listExecutions).not.toHaveBeenCalledWith(
      "chn_1",
      "job_1",
      expect.objectContaining({ limit: 50 }),
    );
    const node = document.querySelector(".react-flow__node[data-id='trigger']");
    expect(phaseLabel(node)).toBe("Failed");
  });

  it("keeps one node's latest phase when another execution request fails", async () => {
    vi.mocked(listExecutions).mockClear();
    vi.mocked(listExecutions).mockImplementation(async (_id, _jobId, params) => {
      if (params?.node_id === "body") throw new Error("down");
      return {
        items: [
          {
            seq: 2,
            node_id: "start",
            status: "failed",
            output_preview: null,
            output_truncated: false,
            preview_only: false,
            preview_totals: {},
          } as NodeExecution,
        ],
        total: 2,
        limit: 1,
        offset: 1,
      };
    });
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
    try {
      await renderCanvas([], graph, {
        catalog: [
          catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
          READ_SPEC,
        ],
        appearance: "browse",
        mutable: false,
        channelId: "chn_1",
        sessionRun: runDetail(graph, "failed", [
          { seq: 1, node_id: "start", status: "succeeded" },
          { seq: 2, node_id: "start", status: "failed" },
          { seq: 3, node_id: "body", status: "succeeded" },
          { seq: 4, node_id: "body", status: "failed" },
        ]),
      });
      await waitFor(() => {
        expect(phaseLabel(document.querySelector(".react-flow__node[data-id='start']"))).toBe(
          "Failed",
        );
      });
      expect(phaseLabel(document.querySelector(".react-flow__node[data-id='body']"))).toBe(
        "Waiting",
      );
    } finally {
      vi.mocked(listExecutions).mockReset();
      vi.mocked(listExecutions).mockResolvedValue({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
      });
    }
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
    expect(tile("save")?.classList.contains("channel-flow-node__icon--teal")).toBe(true);
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

function summarizeExecutions(
  executions: { node_id: string; status: string }[],
): ChannelRunDetail["node_summaries"] {
  const summaries = new Map<string, ChannelRunDetail["node_summaries"][number]>();
  for (const item of executions) {
    const current = summaries.get(item.node_id) ?? {
      node_id: item.node_id,
      execution_count: 0,
      status_counts: {},
    };
    current.execution_count += 1;
    const name = item.status as keyof typeof current.status_counts;
    current.status_counts[name] = (current.status_counts[name] ?? 0) + 1;
    summaries.set(item.node_id, current);
  }
  return [...summaries.values()];
}

function runDetail(
  graph: Graph,
  status: string,
  executions: { seq: number; node_id: string; status: string }[],
): ChannelRunDetail {
  const now = "2026-01-01T00:00:00Z";
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
    node_summaries: summarizeExecutions(executions),
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

    const guarded = screen.getByRole("option", { name: /Requires channel:code_write/ });
    expect(guarded.textContent).toContain("Code");
    expect(guarded.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(guarded);
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(0);

    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));
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

function pickerSearch(): HTMLElement {
  return screen.getByRole("textbox", { name: "Search nodes" });
}

describe("node picker", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  const manual = { ...spec, label: "Manual", summary: "Start here" };
  const code = { ...CODE_SPEC, label: "Code", summary: "Runs Python" };
  const sql = { ...READ_SPEC, label: "SQL", summary: "Query rows" };

  it("filters the open picker by name or summary", async () => {
    await renderCanvas([], EMPTY_GRAPH, { catalog: [manual, code, sql] });
    fireEvent.click(within(screen.getByRole("toolbar")).getByRole("button", { name: "Add" }));
    const search = pickerSearch();
    expect(document.activeElement).toBe(search);
    expect(screen.getByText("Trigger")).toBeTruthy();
    expect(screen.getByRole("option", { name: /Manual/ }).querySelector("svg")).not.toBeNull();

    fireEvent.change(search, { target: { value: "QUERY" } });
    expect(screen.getByRole("option", { name: /SQL/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Manual/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Code/ })).toBeNull();

    fireEvent.change(search, { target: { value: "zzzz" } });
    expect(screen.getByText("No matching nodes")).toBeTruthy();
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("places the second available type from ArrowDown ArrowDown Enter and does not open settings", async () => {
    const onChange = vi.fn();
    await renderCanvas([], EMPTY_GRAPH, { catalog: [manual, code, sql], onChange });
    fireEvent.click(within(screen.getByRole("toolbar")).getByRole("button", { name: "Add" }));
    const search = pickerSearch();
    fireEvent.keyDown(search, { key: "ArrowDown" });
    fireEvent.keyDown(search, { key: "ArrowDown" });
    fireEvent.keyDown(search, { key: "Enter" });

    await waitFor(() => {
      expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);
    });
    const node = document.querySelector(".react-flow__node");
    expect(node?.textContent).toContain("SQL");
    expect(node?.classList.contains("selected")).toBe(true);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.nodes.map((item) => item.type)).toEqual(["read.sql"]);
    expect(saved.edges).toEqual([]);
  });

  it("wires a node placed beside the single selection from the first output that can reach it", async () => {
    const onChange = vi.fn();
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("check", "transform.if", "Check", 40)],
      },
      { catalog: [IF_SPEC, sql], onChange },
    );
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("option", { name: /transform.if/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.type === "read.sql");
    expect(created?.position).toEqual({ x: 320, y: 40 });
    expect(saved.edges).toEqual([
      expect.objectContaining({
        source: { node_id: "check", port: "true" },
        target: { node_id: created?.id, port: "main" },
      }),
    ]);
    expect(document.querySelectorAll(".react-flow__node.selected")).toHaveLength(1);
    expect(document.querySelector(".react-flow__node.selected")?.textContent).toContain("SQL");
    expect(document.querySelector(".channel-node-config")).toBeNull();
  });

  it("places beside the selection without a wire when nothing can connect", async () => {
    const onChange = vi.fn();
    const blocked = catalogSpec("read.sql", [{ port: "main", description: "" }], []);
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("read", "read.sql", "Read", 40)],
      },
      { catalog: [blocked, { ...manual, label: "Manual" }], onChange },
    );
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.edges).toEqual([]);
    expect(saved.nodes.find((item) => item.type === "manual")?.position).toEqual({ x: 320, y: 40 });
    expect(document.querySelector(".channel-node-config")).toBeNull();
  });

  it("opens from Tab on the canvas and leaves Tab alone while settings are open", async () => {
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    node.focus();
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    await act(async () => {
      node.dispatchEvent(tab);
    });
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(pickerSearch());

    fireEvent.keyDown(pickerSearch(), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Search nodes" })).toBeNull();

    openSettings(node);
    node.focus();
    const blocked = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    node.dispatchEvent(blocked);
    expect(blocked.defaultPrevented).toBe(false);
    expect(screen.queryByRole("textbox", { name: "Search nodes" })).toBeNull();
  });

  it("shows a placeholder while a dragged wire is choosing a node, then drops it on Escape", async () => {
    const onChange = vi.fn();
    await renderCanvas([], nodeGraph, { catalog: [spec, sql], onChange });
    await waitFor(() => {
      const node = document.querySelector(".react-flow__node");
      if (!(node instanceof HTMLElement) || node.style.visibility === "hidden") {
        throw new Error("node not measured");
      }
    });

    releaseOutput("Start out output");

    const ghost = document.querySelector(".channel-node-placeholder");
    if (!(ghost instanceof HTMLElement)) throw new Error("missing placeholder");
    expect(ghost.style.width).toBe("208px");
    expect(ghost.style.height).toBe("56px");
    expect(document.querySelector(".channel-node-placeholder__edge")).not.toBeNull();
    expect((screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.keyDown(pickerSearch(), { key: "Escape" });
    expect(document.querySelector(".channel-node-placeholder")).toBeNull();
    expect(document.querySelector(".channel-node-placeholder__edge")).toBeNull();
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);
    expect((screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("adds the next node from an output that has no outgoing edge", async () => {
    const onChange = vi.fn();
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          placed("check", "transform.if", "Check", 40),
          placed("read", "read.sql", "Read", 280),
        ],
        edges: [
          {
            id: "ed_true",
            source: { node_id: "check", port: "true" },
            target: { node_id: "read", port: "main" },
          },
        ],
      },
      { catalog: [IF_SPEC, sql], onChange },
    );
    const card = document.querySelector(".react-flow__node[data-id='check'] .channel-flow-node");
    if (!(card instanceof HTMLElement)) throw new Error("missing if node");
    expect(screen.queryByRole("button", { name: "Add the next step from False" })).toBeNull();

    fireEvent.mouseEnter(card);
    expect(screen.getByRole("button", { name: "Add the next step from False" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add the next step from True" })).toBeNull();
    fireEvent.mouseLeave(card);
    expect(screen.getByRole("button", { name: "Add the next step from False" })).toBeTruthy();

    fireEvent.click(card);
    fireEvent.click(screen.getByRole("button", { name: "Add the next step from False" }));
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "check" && item.id !== "read");
    expect(created?.position).toEqual({ x: 320, y: 40 });
    expect(saved.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: { node_id: "check", port: "false" },
          target: { node_id: created?.id, port: "main" },
        }),
      ]),
    );
    expect(document.querySelector(".channel-node-config")).toBeNull();
    expect(document.querySelectorAll(".react-flow__node.selected")).toHaveLength(1);
  });

  it("keeps the output add control while the pointer moves onto it", async () => {
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("read", "read.sql", "Read", 40)],
      },
      { catalog: [READ_SPEC] },
    );
    const card = document.querySelector(".channel-flow-node");
    if (!(card instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.mouseEnter(card);
    const add = screen.getByRole("button", { name: "Add the next step from Main" });

    vi.useFakeTimers();
    try {
      fireEvent.mouseLeave(add, { relatedTarget: card });
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(screen.getByRole("button", { name: "Add the next step from Main" })).toBeTruthy();

      fireEvent.mouseLeave(card, { relatedTarget: document.body });
      act(() => {
        vi.advanceTimersByTime(149);
      });
      expect(screen.getByRole("button", { name: "Add the next step from Main" })).toBeTruthy();
      fireEvent.mouseEnter(add);
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(screen.getByRole("button", { name: "Add the next step from Main" })).toBeTruthy();

      fireEvent.mouseLeave(card, { relatedTarget: document.body });
      act(() => {
        vi.advanceTimersByTime(149);
      });
      expect(screen.getByRole("button", { name: "Add the next step from Main" })).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(51);
      });
      expect(screen.queryByRole("button", { name: "Add the next step from Main" })).toBeNull();

      fireEvent.click(card);
      expect(screen.getByRole("button", { name: "Add the next step from Main" })).toBeTruthy();
      fireEvent.mouseLeave(card, { relatedTarget: document.body });
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(screen.getByRole("button", { name: "Add the next step from Main" })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("inserts a node into an edge and undoes both new edges in one step", async () => {
    const onChange = vi.fn();
    const sqlSpec = { ...READ_SPEC, label: "SQL", summary: "Query rows" };
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("left", "read.sql", "Left", 20), placed("right", "read.sql", "Right", 300)],
        edges: [
          {
            id: "ed_link",
            source: { node_id: "left", port: "main" },
            target: { node_id: "right", port: "main" },
          },
        ],
      },
      { catalog: [manual, sqlSpec], onChange },
    );
    const edge = await screen.findByRole("group", { name: "Main to Main" });
    const path = edge.querySelector(".react-flow__edge-path");
    if (path) fireEvent.mouseOver(path);
    fireEvent.click(edge);
    fireEvent.click(screen.getByRole("button", { name: "Insert node" }));
    expect(screen.queryByRole("option", { name: /Manual/ })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "left" && item.id !== "right");
    expect(created?.position).toEqual({ x: 160, y: 40 });
    expect(saved.edges).toHaveLength(2);
    expect(saved.edges.map((item) => [item.source.node_id, item.target.node_id])).toEqual([
      ["left", created?.id],
      [created?.id, "right"],
    ]);
    expect(document.querySelector(".channel-node-config")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const restored = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(restored.nodes.map((item) => item.id)).toEqual(["left", "right"]);
      expect(restored.edges.map((item) => item.id)).toEqual(["ed_link"]);
    });
  });

  it("hides trigger types once the graph already has one", async () => {
    await renderCanvas([], nodeGraph, { catalog: [manual, sql] });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.queryByRole("option", { name: /Manual/ })).toBeNull();
    expect(screen.getByRole("option", { name: /SQL/ })).toBeTruthy();
  });

  it("disables add and hides the port and edge insert controls while the graph is locked", async () => {
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("left", "read.sql", "Left", 20), placed("right", "read.sql", "Right", 300)],
        edges: [
          {
            id: "ed_link",
            source: { node_id: "left", port: "main" },
            target: { node_id: "right", port: "main" },
          },
        ],
      },
      { mutable: false, catalog: [READ_SPEC] },
    );
    expect((screen.getByRole("button", { name: "Add" }) as HTMLButtonElement).disabled).toBe(true);
    const card = document.querySelector(".channel-flow-node");
    if (!(card instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(card);
    fireEvent.mouseEnter(card);
    expect(screen.queryByRole("button", { name: /Add the next step from/ })).toBeNull();

    const edge = await screen.findByRole("group", { name: "Main to Main" });
    const path = edge.querySelector(".react-flow__edge-path");
    if (path) fireEvent.mouseOver(path);
    fireEvent.click(edge);
    expect(screen.queryByRole("button", { name: "Insert node" })).toBeNull();

    card.focus();
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    card.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(false);
    expect(screen.queryByRole("textbox", { name: "Search nodes" })).toBeNull();
  });
});

function installClipboard(readText = vi.fn().mockResolvedValue("")) {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText, readText },
  });
  return { writeText, readText };
}

function fragmentText(item: Graph["nodes"][number]): string {
  return JSON.stringify({
    kind: "refraq.channel.fragment",
    version: 1,
    nodes: [item],
    edges: [],
    notes: [],
  });
}

function dispatchPaste(target: Element, text: string) {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", {
    value: { getData: () => text },
  });
  target.dispatchEvent(event);
  return event;
}

function pressKey(target: Element, init: KeyboardEventInit) {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

const brought: Graph["nodes"][number] = {
  id: "nd_foreign",
  ref: "read_sql",
  type: "read.sql",
  name: "Load",
  position: { x: 10, y: 20 },
  config: { sql: "select 1" },
  on_error: "stop",
  retry: null,
};

function loadGraph(): Graph {
  return {
    ...EMPTY_GRAPH,
    nodes: [placed("load", "read.sql", "Load", 40)],
  };
}

describe("channel canvas clipboard and menus", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("writes the selection to the clipboard on Ctrl+C and leaves the graph alone", async () => {
    const onChange = vi.fn();
    const { writeText } = installClipboard();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.click(node);
    const copied = pressKey(node, { key: "c", code: "KeyC", ctrlKey: true });

    expect(copied.defaultPrevented).toBe(true);
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const envelope = JSON.parse(String(writeText.mock.calls[0]?.[0])) as {
      kind: string;
      notes: unknown[];
      nodes: { id: string }[];
    };
    expect(envelope.kind).toBe("refraq.channel.fragment");
    expect(envelope.notes).toEqual([]);
    expect(envelope.nodes.map((item) => item.id)).toEqual(["load"]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not intercept Ctrl+C while focus is in a field", async () => {
    const { writeText } = installClipboard();
    await renderCanvas([], nodeGraph);
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    openSettings(node);
    const name = screen.getByRole("textbox", { name: "Name" });

    const copied = pressKey(name, { key: "c", code: "KeyC", ctrlKey: true });

    expect(copied.defaultPrevented).toBe(false);
    expect(writeText).not.toHaveBeenCalled();
  });

  it("pastes from the paste event, selects the new node, and undoes it in one step", async () => {
    const onChange = vi.fn();
    const { readText } = installClipboard();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    dispatchPaste(node, fragmentText({ ...brought, name: "Brought", ref: "brought" }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.nodes.map((item) => item.id)).toContain("load");
    const created = saved.nodes.find((item) => item.id !== "load");
    expect(created?.name).toBe("Brought");
    expect(created?.position).toEqual({ x: 50, y: 60 });
    expect(created?.config).toEqual({ sql: "select 1" });
    expect(saved.nodes.find((item) => item.id === "load")?.position).toEqual({ x: 40, y: 40 });
    expect(document.querySelectorAll(".react-flow__node.selected")).toHaveLength(1);
    expect(document.querySelector(".react-flow__node.selected")?.getAttribute("data-id")).toBe(
      created?.id,
    );
    expect(readText).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const restored = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(restored.nodes.map((item) => item.id)).toEqual(["load"]);
    });
    expect((screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("duplicates the selection with Ctrl+D without using the clipboard", async () => {
    const onChange = vi.fn();
    const { writeText, readText } = installClipboard();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.click(node);
    pressKey(node, { key: "d", code: "KeyD", ctrlKey: true });

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "load");
    expect(created?.name).toBe("Load 2");
    expect(created?.ref).toBe("load_2");
    expect(created?.position).toEqual({ x: 80, y: 80 });
    expect(saved.nodes.find((item) => item.id === "load")?.position).toEqual({ x: 40, y: 40 });
    expect(document.querySelector(".react-flow__node.selected")?.getAttribute("data-id")).toBe(
      created?.id,
    );
    expect(writeText).not.toHaveBeenCalled();
    expect(readText).not.toHaveBeenCalled();
  });

  it("cuts the selection and restores it in one undo", async () => {
    const onChange = vi.fn();
    const { writeText } = installClipboard();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.click(node);
    pressKey(node, { key: "x", code: "KeyX", ctrlKey: true });

    await waitFor(() => expect(document.querySelector(".react-flow__node")).toBeNull());
    const envelope = JSON.parse(String(writeText.mock.calls[0]?.[0])) as {
      nodes: { id: string }[];
    };
    expect(envelope.nodes.map((item) => item.id)).toEqual(["load"]);

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const restored = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(restored.nodes.map((item) => item.id)).toEqual(["load"]);
    });
  });

  it("leaves the graph unchanged for cut, paste, and duplicate while a run lock is held", async () => {
    const onChange = vi.fn();
    const { writeText } = installClipboard();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], mutable: false, onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.click(node);
    pressKey(node, { key: "x", code: "KeyX", ctrlKey: true });
    pressKey(node, { key: "d", code: "KeyD", ctrlKey: true });
    dispatchPaste(node, fragmentText(brought));
    pressKey(node, { key: "c", code: "KeyC", ctrlKey: true });

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);
  });

  it("explains a skipped trigger inside the canvas", async () => {
    const onChange = vi.fn();
    installClipboard();
    await renderCanvas([], nodeGraph, { onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    dispatchPaste(
      node,
      fragmentText({
        ...nodeGraph.nodes[0]!,
        id: "nd_other",
        ref: "manual_2",
        name: "Other",
      }),
    );

    const note = await screen.findByText(
      "Skipped 1 trigger nodes: a channel can have only one trigger",
    );
    expect(note.getAttribute("aria-live")).toBe("polite");
    expect(note.className).toContain("channel-canvas-clipboard-note");
    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(1);
  });

  it("duplicates the selected node from its toolbar", async () => {
    const onChange = vi.fn();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], onChange });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);

    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.nodes.map((item) => item.name).sort()).toEqual(["Load", "Load 2"]);
    expect(saved.nodes.find((item) => item.id === "load")?.position).toEqual({ x: 40, y: 40 });
  });

  it("opens a node menu that selects the node and runs its actions", async () => {
    const onRun = vi.fn();
    const { writeText } = installClipboard();
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC], onRun });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.contextMenu(node);
    expect(node.classList.contains("selected")).toBe(true);
    expect(await screen.findByRole("menuitem", { name: /Settings/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Run to this node/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Duplicate/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Copy/ }).textContent).toContain("Ctrl+C");
    expect(screen.getByRole("menuitem", { name: /Cut/ })).toBeTruthy();
    const remove = screen.getByRole("menuitem", { name: /Delete/ });
    expect(remove.className).toContain("channel-canvas-menu__danger");

    fireEvent.click(screen.getByRole("menuitem", { name: /Settings/ }));
    expect(document.querySelector(".channel-node-config")).not.toBeNull();

    fireEvent.contextMenu(node);
    fireEvent.click(await screen.findByRole("menuitem", { name: /Run to this node/ }));
    expect(onRun).toHaveBeenCalledWith("load");

    fireEvent.contextMenu(node);
    fireEvent.click(await screen.findByRole("menuitem", { name: /^Copy/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
  });

  it("closes the menu on Escape and keeps the selection", async () => {
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC] });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.contextMenu(node);
    expect(await screen.findByRole("menuitem", { name: /Copy/ })).toBeTruthy();
    expect(node.classList.contains("selected")).toBe(true);

    fireEvent.keyDown(node, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("menuitem", { name: /Copy/ })).toBeNull());
    expect(node.classList.contains("selected")).toBe(true);
  });

  it("shows the multi-selection menu without settings", async () => {
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("load", "read.sql", "Load", 40), placed("next", "read.sql", "Next", 280)],
      },
      { catalog: [READ_SPEC] },
    );
    const node = (id: string) => {
      const found = document.querySelector(`.react-flow__node[data-id="${id}"]`);
      if (!(found instanceof HTMLElement)) throw new Error(`missing ${id}`);
      return found;
    };
    fireEvent.click(node("load"));
    fireEvent.keyDown(window, { key: "Shift", code: "ShiftLeft" });
    fireEvent.click(node("next"), { shiftKey: true });

    fireEvent.contextMenu(node("next"));

    expect(await screen.findByRole("menuitem", { name: /Duplicate/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Copy/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Cut/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Delete/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /Settings/ })).toBeNull();
  });

  it("inserts from an edge menu without deleting the edge, and deletes from that menu", async () => {
    const onChange = vi.fn();
    const sqlSpec = { ...READ_SPEC, label: "SQL", summary: "Query rows" };
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [placed("left", "read.sql", "Left", 20), placed("right", "read.sql", "Right", 300)],
        edges: [
          {
            id: "ed_link",
            source: { node_id: "left", port: "main" },
            target: { node_id: "right", port: "main" },
          },
        ],
      },
      { catalog: [sqlSpec], onChange },
    );
    const edge = await screen.findByRole("group", { name: "Main to Main" });

    fireEvent.contextMenu(edge);
    fireEvent.click(await screen.findByRole("menuitem", { name: /Insert node/ }));

    expect(screen.getByRole("textbox", { name: "Search nodes" })).toBeTruthy();
    expect(screen.getByRole("option", { name: /SQL/ })).toBeTruthy();
    expect(document.querySelector(".react-flow__edge")).not.toBeNull();
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Search nodes" }), { key: "Escape" });
    fireEvent.contextMenu(edge);
    fireEvent.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.edges).toEqual([]);
  });

  it("adds, pastes, and fits from the empty-canvas menu", async () => {
    const onChange = vi.fn();
    const readText = vi.fn().mockResolvedValue(
      fragmentText({ ...brought, name: "Brought", ref: "brought" }),
    );
    installClipboard(readText);
    await renderCanvas([], EMPTY_GRAPH, { catalog: [READ_SPEC], onChange });
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");

    fireEvent.contextMenu(pane);
    expect(await screen.findByRole("menuitem", { name: /Fit view/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: /Add a node here/ }));
    expect(screen.getByRole("option", { name: /read\.sql/ })).toBeTruthy();

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Search nodes" }), { key: "Escape" });
    fireEvent.contextMenu(pane);
    const paste = await screen.findByRole("menuitem", { name: /Paste/ });
    await waitFor(() => expect((paste as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(paste);
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(readText).toHaveBeenCalled();
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.nodes.map((item) => item.name)).toEqual(["Brought"]);
  });

  it("disables pane paste and tells the user to use the shortcut when the clipboard cannot be read", async () => {
    const readText = vi.fn().mockRejectedValue(new Error("denied"));
    installClipboard(readText);
    await renderCanvas([], EMPTY_GRAPH);
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");

    fireEvent.contextMenu(pane);

    expect(await screen.findByText("Use Ctrl+V or Cmd+V to paste")).toBeTruthy();
    const paste = screen.getByRole("menuitem", { name: /Paste/ });
    expect((paste as HTMLButtonElement).disabled || paste.getAttribute("aria-disabled")).toBeTruthy();
  });

  it("keeps only settings, copy, and fit view while browsing", async () => {
    await renderCanvas([], loadGraph(), { appearance: "browse", mutable: false, catalog: [READ_SPEC] });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.contextMenu(node);
    expect(await screen.findByRole("menuitem", { name: /Settings/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Copy/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /Duplicate/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Cut/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Delete/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Run to this node/ })).toBeNull();

    fireEvent.keyDown(document.body, { key: "Escape" });
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");
    fireEvent.contextMenu(pane);
    expect(await screen.findByRole("menuitem", { name: /Fit view/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /Add a node here/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Add a note/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Paste/ })).toBeNull();
  });

  it("hides graph-changing menu items while a run lock is held", async () => {
    await renderCanvas([], loadGraph(), { mutable: false, catalog: [READ_SPEC] });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");

    fireEvent.contextMenu(node);
    expect(await screen.findByRole("menuitem", { name: /Settings/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Copy/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Run to this node/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /Duplicate/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Cut/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Delete/ })).toBeNull();
  });
});

const keptNote = {
  id: "nt_kept",
  position: { x: 80, y: 200 },
  size: { width: 240, height: 120 },
  text: "keep this",
};

function graphWithNote(): Graph {
  return { ...nodeGraph, notes: [keptNote] };
}

describe("canvas notes", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("adds a note from the toolbar, keeps the typed lines, and undoes that text in one step", async () => {
    const onChange = vi.fn();
    await renderCanvas([], nodeGraph, { onChange });

    fireEvent.click(screen.getByRole("button", { name: "Note" }));

    const field = screen.getByRole("textbox", { name: "Note" });
    expect(document.activeElement).toBe(field);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    expect(document.querySelector(".react-flow__node-toolbar")).toBeNull();
    expect(document.querySelector(".react-flow__node-note")).not.toBeNull();

    fireEvent.change(field, { target: { value: "hello\nthere" } });
    fireEvent.blur(field);

    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.notes).toEqual([
        expect.objectContaining({
          text: "hello\nthere",
          size: { width: 240, height: 120 },
          position: { x: 160, y: 120 },
        }),
      ]);
    });
    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(saved.nodes.map((item) => item.id)).toEqual(["nd_1"]);
    expect(saved.notes?.[0]?.id).toMatch(/^nt_[0-9a-f]{12}$/);

    const callsBeforeUndo = onChange.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(onChange.mock.calls.length).toBeGreaterThan(callsBeforeUndo));
    const restored = onChange.mock.calls.at(-1)?.[0] as Graph;
    expect(restored.notes).toEqual([expect.objectContaining({ text: "" })]);
    expect(restored.nodes.map((item) => item.id)).toEqual(["nd_1"]);
  });

  it("moves a selected note and deletes it without opening settings", async () => {
    const onChange = vi.fn();
    await renderCanvas([], graphWithNote(), { onChange });
    const note = document.querySelector(".react-flow__node-note");
    if (!(note instanceof HTMLElement)) throw new Error("missing note");

    fireEvent.click(note);
    expect(note.classList.contains("draggable")).toBe(true);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    expect(document.querySelector(".react-flow__node-toolbar")).toBeNull();

    note.focus();
    fireEvent.keyDown(note, { key: "ArrowRight" });

    await waitFor(() => {
      const moved = onChange.mock.calls.at(-1)?.[0] as Graph | undefined;
      expect(moved?.notes?.[0]?.position).toEqual({ x: keptNote.position.x + 8, y: keptNote.position.y });
    });

    fireEvent.keyDown(document, { key: "Delete", code: "Delete" });
    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.notes).toBeUndefined();
      expect(saved.nodes.map((item) => item.id)).toEqual(["nd_1"]);
    });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const restored = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(restored.notes?.[0]?.text).toBe("keep this");
    });
  });

  it("edits a note on double-click and leaves settings closed", async () => {
    const onChange = vi.fn();
    await renderCanvas([], graphWithNote(), { onChange });
    const note = document.querySelector(".react-flow__node-note");
    if (!(note instanceof HTMLElement)) throw new Error("missing note");

    fireEvent.doubleClick(note);
    expect(document.querySelector(".channel-node-config")).toBeNull();
    const field = screen.getByRole("textbox", { name: "Note" });
    expect(field).toHaveProperty("value", "keep this");

    note.focus();
    fireEvent.keyDown(note, { key: "Enter" });
    expect(document.querySelector(".channel-node-config")).toBeNull();

    fireEvent.change(field, { target: { value: "keep this" } });
    fireEvent.keyDown(field, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelector(".channel-note")?.textContent).toContain("keep this");
  });

  it("adds a note at the pointer from the empty pane menu", async () => {
    const onChange = vi.fn();
    await renderCanvas([], EMPTY_GRAPH, { onChange });
    const pane = document.querySelector(".react-flow__pane");
    if (!(pane instanceof HTMLElement)) throw new Error("missing pane");

    fireEvent.contextMenu(pane, { clientX: 40, clientY: 48 });
    fireEvent.click(await screen.findByRole("menuitem", { name: /Add a note/ }));

    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Note" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Note" }), { target: { value: "here" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Note" }));
    await waitFor(() => {
      const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
      expect(saved.nodes).toEqual([]);
      expect(saved.notes?.[0]?.text).toBe("here");
      expect(saved.notes?.[0]?.size).toEqual({ width: 240, height: 120 });
    });
  });

  it("paints a note in a pale minimap color", async () => {
    localStorage.setItem("refraq.channelCanvas.minimap", "1");
    await renderCanvas([], graphWithNote());
    await waitFor(() => {
      const fills = [...document.querySelectorAll(".react-flow__minimap-node")].map(
        (node) => (node as SVGElement).style.fill,
      );
      expect(fills).toContain("var(--mantine-color-yellow-light)");
      expect(fills).toContain("var(--mantine-color-orange-filled)");
    });
  });

  it("stays read-only while browsing, with no resize handles", async () => {
    await renderCanvas([], graphWithNote(), { appearance: "browse", mutable: false });
    expect(screen.queryByRole("button", { name: "Note" })).toBeNull();
    const note = document.querySelector(".react-flow__node-note");
    if (!(note instanceof HTMLElement)) throw new Error("missing note");
    expect(note.textContent).toContain("keep this");
    expect(document.querySelector(".react-flow__resize-control")).toBeNull();

    fireEvent.click(note);
    fireEvent.doubleClick(note);
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
    expect(document.querySelector(".react-flow__resize-control")).toBeNull();
    expect(document.querySelector(".channel-node-config")).toBeNull();
  });

  it("refuses note edits while a run lock is held", async () => {
    const onChange = vi.fn();
    await renderCanvas([], graphWithNote(), { mutable: false, onChange });
    expect((screen.getByRole("button", { name: "Note" }) as HTMLButtonElement).disabled).toBe(true);
    const note = document.querySelector(".react-flow__node-note");
    if (!(note instanceof HTMLElement)) throw new Error("missing note");

    fireEvent.click(note);
    fireEvent.doubleClick(note);
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
    expect(document.querySelector(".react-flow__resize-control")).toBeNull();

    fireEvent.keyDown(document, { key: "Delete", code: "Delete" });
    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelector(".react-flow__node-note")?.textContent).toContain("keep this");
  });
});

describe("canvas motion", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  function finishAnimation(element: Element, animationName: string) {
    const event = new Event("animationend", { bubbles: true });
    Object.defineProperty(event, "animationName", { value: animationName });
    act(() => {
      element.dispatchEvent(event);
    });
  }

  async function renderPhase(
    graph: Graph,
    catalog: NodeTypeSpec[],
    sessionRun: ChannelRunDetail | null,
  ) {
    const { ChannelCanvas } = await import("@/features/channels/ChannelCanvas");
    const element = (run: ChannelRunDetail | null) =>
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ChannelCanvas, {
          graph,
          catalog,
          appearance: "browse",
          mutable: false,
          problems: [],
          onChange: vi.fn(),
          sessionRun: run,
        }),
      );
    const view = render(element(sessionRun));
    return {
      show(next: ChannelRunDetail | null) {
        view.rerender(element(next));
      },
    };
  }

  function statusOf(nodeId: string): Element | null {
    return document.querySelector(
      `.react-flow__node[data-id='${nodeId}'] .channel-flow-node__status`,
    );
  }

  it("fades in a node created in this session and removes the class when the animation ends", async () => {
    await renderCanvas();
    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));

    const entering = document.querySelector(".channel-flow-node--entering");
    if (!(entering instanceof HTMLElement)) throw new Error("missing entering node");
    finishAnimation(entering, "channel-flow-node-enter");
    expect(document.querySelector(".channel-flow-node--entering")).toBeNull();
    expect(document.querySelector(".channel-flow-node")).not.toBeNull();
  });

  it("does not fade in a node that undo or redo restores", async () => {
    await renderCanvas();
    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));
    expect(document.querySelector(".channel-flow-node--entering")).not.toBeNull();

    fireEvent.click(within(toolbar).getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(document.querySelector(".react-flow__node")).toBeNull();
    });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Redo" }));
    await waitFor(() => {
      expect(document.querySelector(".react-flow__node")).not.toBeNull();
    });
    expect(document.querySelector(".channel-flow-node--entering")).toBeNull();
  });

  it("fades in a note created in this session and leaves a loaded note still", async () => {
    await renderCanvas([], graphWithNote());
    expect(document.querySelector(".channel-flow-node--entering")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Note" }));
    const created = document.querySelector(".channel-note.channel-flow-node--entering");
    expect(created).not.toBeNull();
    expect(document.querySelectorAll(".channel-flow-node--entering")).toHaveLength(1);
  });

  it("fades in a duplicated node and not the node it was copied from", async () => {
    await renderCanvas([], loadGraph(), { catalog: [READ_SPEC] });
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    pressKey(node, { key: "d", code: "KeyD", ctrlKey: true });

    await waitFor(() => {
      expect(document.querySelectorAll(".channel-flow-node--entering")).toHaveLength(1);
    });
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(2);
    expect(
      document
        .querySelector(".channel-flow-node--entering")
        ?.closest(".react-flow__node")
        ?.getAttribute("data-id"),
    ).not.toBe("load");
  });

  it("draws a newly connected edge and clears that class when the stroke finishes", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("check", "transform.if", "Check", 20), placed("read", "read.sql", "Read", 280)],
      edges: [
        {
          id: "ed_old",
          source: { node_id: "check", port: "false" },
          target: { node_id: "read", port: "main" },
        },
      ],
    }, { catalog: [IF_SPEC, READ_SPEC] });

    const loaded = await screen.findByRole("group", { name: "False to Main" });
    expect(loaded.classList.contains("channel-flow-edge--draw")).toBe(false);

    fireEvent.click(await screen.findByRole("button", { name: "Check True output" }));
    fireEvent.click(await screen.findByRole("button", { name: "Read Main input" }));
    const created = await screen.findByRole("group", { name: "True to Main" });
    expect(created.classList.contains("channel-flow-edge--draw")).toBe(true);
    expect(loaded.classList.contains("channel-flow-edge--draw")).toBe(false);

    finishAnimation(created, "channel-flow-edge-draw");
    expect(created.classList.contains("channel-flow-edge--draw")).toBe(false);
  });

  it("does not draw an edge that redo restores", async () => {
    await renderCanvas([], {
      ...EMPTY_GRAPH,
      nodes: [placed("check", "transform.if", "Check", 20), placed("read", "read.sql", "Read", 280)],
    }, { catalog: [IF_SPEC, READ_SPEC] });

    fireEvent.click(await screen.findByRole("button", { name: "Check True output" }));
    fireEvent.click(await screen.findByRole("button", { name: "Read Main input" }));
    expect((await screen.findByRole("group", { name: "True to Main" })).classList.contains(
      "channel-flow-edge--draw",
    )).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(screen.queryByRole("group", { name: "True to Main" })).toBeNull();
    });
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    const restored = await screen.findByRole("group", { name: "True to Main" });
    expect(restored.classList.contains("channel-flow-edge--draw")).toBe(false);
  });

  it("keeps a new edge into the running node live instead of drawing it", async () => {
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [
        placed("start", "trigger.manual", "Start", 20),
        placed("body", "read.sql", "Body", 280),
        placed("extra", "read.sql", "Extra", 520),
      ],
      edges: [
        {
          id: "ed_old",
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
      sessionRun: runDetail(graph, "running", [
        { seq: 1, node_id: "start", status: "succeeded" },
        { seq: 2, node_id: "body", status: "running" },
      ]),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Extra Main output" }));
    fireEvent.click(await screen.findByRole("button", { name: "Body Main input" }));
    const edges = await screen.findAllByRole("group", { name: "Main to Main" });
    expect(edges).toHaveLength(2);
    expect(edges.every((edge) => edge.classList.contains("channel-flow-edge--live"))).toBe(true);
    expect(edges.some((edge) => edge.classList.contains("channel-flow-edge--draw"))).toBe(false);
  });

  it("does not pop a status icon that is already succeeded on first load", async () => {
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [placed("start", "trigger.manual", "Start", 20)],
    };
    await renderCanvas([], graph, {
      catalog: [catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true)],
      appearance: "browse",
      mutable: false,
      sessionRun: runDetail(graph, "succeeded", [
        { seq: 1, node_id: "start", status: "succeeded" },
      ]),
    });

    const status = statusOf("start");
    expect(status?.getAttribute("aria-label")).toBe("Succeeded");
    expect(status?.classList.contains("channel-flow-node__status--pop")).toBe(false);
  });

  it("pops the status icon when a running phase becomes succeeded, and not from waiting", async () => {
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
    const catalog = [
      catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true),
      READ_SPEC,
    ];
    const view = await renderPhase(
      graph,
      catalog,
      runDetail(graph, "running", [{ seq: 1, node_id: "start", status: "running" }]),
    );
    expect(statusOf("start")?.getAttribute("aria-label")).toBe("Running");
    expect(statusOf("start")?.classList.contains("channel-flow-node__status--pop")).toBe(false);
    expect(statusOf("body")?.getAttribute("aria-label")).toBe("Waiting");
    expect(statusOf("body")?.classList.contains("channel-flow-node__status--pop")).toBe(false);

    view.show(
      runDetail(graph, "running", [
        { seq: 1, node_id: "start", status: "succeeded" },
        { seq: 2, node_id: "body", status: "succeeded" },
      ]),
    );

    const started = statusOf("start");
    if (!(started instanceof HTMLElement)) throw new Error("missing succeeded mark");
    expect(started.classList.contains("channel-flow-node__status--pop")).toBe(true);
    expect(statusOf("body")?.classList.contains("channel-flow-node__status--pop")).toBe(false);
    finishAnimation(started, "channel-flow-status-pop");
    expect(statusOf("start")?.classList.contains("channel-flow-node__status--pop")).toBe(false);
    expect(statusOf("start")?.getAttribute("aria-label")).toBe("Succeeded");
  });

  it("pops the status icon when a node with no phase becomes succeeded", async () => {
    const graph: Graph = {
      ...EMPTY_GRAPH,
      nodes: [placed("start", "trigger.manual", "Start", 20)],
    };
    const catalog = [catalogSpec("trigger.manual", [], [{ port: "main", description: "" }], true)];
    const view = await renderPhase(graph, catalog, null);
    expect(statusOf("start")).toBeNull();

    view.show(
      runDetail(graph, "succeeded", [{ seq: 1, node_id: "start", status: "succeeded" }]),
    );
    expect(statusOf("start")?.classList.contains("channel-flow-node__status--pop")).toBe(true);
  });

  it("skips the entering class and uses a zero viewport duration when motion is reduced", async () => {
    window.matchMedia = (query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    expect(canvasViewportDuration()).toBe(0);

    await renderCanvas();
    const toolbar = screen.getByRole("toolbar", { name: "Canvas tools" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));
    expect(document.querySelector(".react-flow__node")).not.toBeNull();
    expect(document.querySelector(".channel-flow-node--entering")).toBeNull();

    fireEvent.click(within(toolbar).getByRole("button", { name: "Note" }));
    expect(document.querySelector(".channel-note")).not.toBeNull();
    expect(document.querySelector(".channel-flow-node--entering")).toBeNull();
  });

  it("keeps canvas motion inside the no-preference media query", () => {
    const css = readFileSync(resolve(__dirname, "ChannelCanvas.css"), "utf8");
    const motion = mediaBlocks(css, "prefers-reduced-motion: no-preference").join("\n");
    const names = [
      "channel-flow-node-enter",
      "channel-flow-status-spin",
      "channel-flow-status-pop",
      "channel-flow-edge-draw",
    ];
    for (const name of names) {
      expect(motion).toContain(`@keyframes ${name}`);
      expect(css.split(`@keyframes ${name}`).length - 1).toBe(
        motion.split(`@keyframes ${name}`).length - 1,
      );
    }

    const enter = motion.match(/@keyframes channel-flow-node-enter \{([\s\S]*?)\n  \}/)?.[1] ?? "";
    expect(enter).toMatch(/opacity:\s*0/);
    expect(enter).toMatch(/scale\(0\.96\)/);
    expect(enter).not.toMatch(/\b(?:width|height|margin|top|left)\s*:/);
    expect(motion).toMatch(
      /\.channel-flow-node--entering[\s\S]*var\(--refraq-motion-base\)[\s\S]*var\(--refraq-ease-enter\)/,
    );

    const pop = motion.match(/@keyframes channel-flow-status-pop \{([\s\S]*?)\n  \}/)?.[1] ?? "";
    expect(pop).toMatch(/opacity:\s*0/);
    expect(pop).toMatch(/scale\(0\.6\)/);
    expect(pop).not.toMatch(/\b(?:width|height|margin|top|left)\s*:/);

    const spin = motion.match(/@keyframes channel-flow-status-spin \{([\s\S]*?)\n  \}/)?.[1] ?? "";
    expect(spin).toMatch(/rotate\(360deg\)/);
    expect(motion).toMatch(/channel-flow-status-spin 1s linear infinite/);

    const draw = motion.match(/@keyframes channel-flow-edge-draw \{([\s\S]*?)\n  \}/)?.[1] ?? "";
    expect(draw).toMatch(/stroke-dashoffset:\s*0/);
    expect(draw).not.toMatch(/\b(?:width|height|margin|top|left)\s*:/);
    expect(motion).toMatch(
      /channel-flow-edge--draw[\s\S]*stroke-dasharray:\s*var\(--channel-edge-length\)/,
    );
    expect(motion).toMatch(
      /channel-flow-edge--draw[\s\S]*var\(--refraq-motion-slow\)/,
    );
    expect(motion).toMatch(/stroke-width var\(--refraq-motion-fast\) var\(--refraq-ease-standard\)/);
    expect(motion).toMatch(/box-shadow var\(--refraq-motion-fast\) var\(--refraq-ease-standard\)/);
  });
});

describe("adding inside a frame", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  const sql = { ...READ_SPEC, label: "SQL", summary: "Query rows" };

  it("parents a node added from a child output to that frame", async () => {
    const onChange = vi.fn();
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          { ...placed("walk", "volume.for", "Walk", 0), position: { x: 100, y: 40 } },
          { ...placed("step", "read.sql", "Step", 0), position: { x: 40, y: 80 }, parent: "walk" },
        ],
      },
      { catalog: [FOR_SPEC, sql], onChange },
    );
    const card = document.querySelector(".react-flow__node[data-id='step'] .channel-flow-node");
    if (!(card instanceof HTMLElement)) throw new Error("missing step");
    fireEvent.click(card);
    fireEvent.click(screen.getByRole("button", { name: "Add the next step from Main" }));
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "walk" && item.id !== "step");
    expect(created).toMatchObject({ parent: "walk", position: { x: 320, y: 80 } });
    expect(saved.edges).toEqual([
      expect.objectContaining({
        source: { node_id: "step", port: "main" },
        target: { node_id: created?.id, port: "main" },
      }),
    ]);
  });

  it("places a nested done card in the outer frame", async () => {
    const onChange = vi.fn();
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          { ...placed("outer", "volume.for", "Outer", 0), position: { x: 100, y: 80 } },
          {
            ...placed("inner", "volume.for", "Inner", 0),
            position: { x: 40, y: 48 },
            parent: "outer",
          },
        ],
      },
      { catalog: [FOR_SPEC, sql], onChange },
    );
    const card = document.querySelector(".react-flow__node[data-id='inner'] .channel-flow-node");
    if (!(card instanceof HTMLElement)) throw new Error("missing inner");
    fireEvent.click(card);
    fireEvent.click(screen.getByRole("button", { name: "Add the next step from Done" }));
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "outer" && item.id !== "inner");
    expect(created).toMatchObject({ parent: "outer", position: { x: 432, y: 48 } });
    expect(saved.edges).toEqual([
      expect.objectContaining({
        source: { node_id: "inner", port: "done" },
        target: { node_id: created?.id, port: "main" },
      }),
    ]);
  });

  it("inserts on an each edge inside the frame", async () => {
    const onChange = vi.fn();
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          { ...placed("walk", "volume.for", "Walk", 0), position: { x: 100, y: 40 } },
          { ...placed("step", "read.sql", "Step", 0), position: { x: 80, y: 60 }, parent: "walk" },
        ],
        edges: [
          {
            id: "each",
            source: { node_id: "walk", port: "each" },
            target: { node_id: "step", port: "main" },
          },
        ],
      },
      { catalog: [FOR_SPEC, sql], onChange },
    );
    const edge = await screen.findByRole("group", { name: "Each to Main" });
    const path = edge.querySelector(".react-flow__edge-path");
    if (path) fireEvent.mouseOver(path);
    fireEvent.click(edge);
    fireEvent.click(screen.getByRole("button", { name: "Insert node" }));
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    const saved = onChange.mock.calls.at(-1)?.[0] as Graph;
    const created = saved.nodes.find((item) => item.id !== "walk" && item.id !== "step");
    expect(created).toMatchObject({ parent: "walk", position: { x: 40, y: 30 } });
    expect(saved.edges.map((item) => [item.source.node_id, item.source.port, item.target.node_id])).toEqual([
      ["walk", "each", created?.id],
      [created?.id, "main", "step"],
    ]);
  });

  it("closes the picker and explains when the new node would cross the frame", async () => {
    const onChange = vi.fn();
    await renderCanvas(
      [],
      {
        ...EMPTY_GRAPH,
        nodes: [
          { ...placed("walk", "volume.for", "Walk", 0), position: { x: 40, y: 40 } },
          { ...placed("step", "read.sql", "Step", 0), position: { x: 48, y: 48 }, parent: "walk" },
          { ...placed("out", "read.sql", "Out", 0), position: { x: 600, y: 40 } },
        ],
        edges: [
          {
            id: "leak",
            source: { node_id: "step", port: "main" },
            target: { node_id: "out", port: "main" },
          },
        ],
      },
      { catalog: [FOR_SPEC, sql], onChange },
    );
    const edge = await screen.findByRole("group", { name: "Main to Main" });
    const path = edge.querySelector(".react-flow__edge-path");
    if (path) fireEvent.mouseOver(path);
    fireEvent.click(edge);
    fireEvent.click(screen.getByRole("button", { name: "Insert node" }));
    fireEvent.click(screen.getByRole("option", { name: /SQL/ }));

    expect(screen.queryByRole("textbox", { name: "Search nodes" })).toBeNull();
    const note = screen.getByText("This node cannot be added here.");
    expect(note.getAttribute("aria-live")).toBe("polite");
    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelectorAll(".react-flow__node")).toHaveLength(3);
  });
});

