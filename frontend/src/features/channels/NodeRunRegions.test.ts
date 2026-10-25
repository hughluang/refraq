/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getExecutionOutput, listRounds, nodeSample } from "@/features/channels/api";
import { ResultRegion, SampleBar, UpstreamRegion, useNodeSample } from "@/features/channels/NodeRunRegions";
import {
  EMPTY_GRAPH,
  type ChannelRunDetail,
  type Graph,
  type NodeSample,
  type NodeSampleUpstream,
  type NodeTypeSpec,
  type OutputView,
} from "@/features/channels/types";

vi.mock("@/features/channels/api", () => ({
  nodeSample: vi.fn(),
  listRounds: vi.fn(() => Promise.resolve({ items: [], total: 0, limit: 50, offset: 0 })),
  listExecutions: vi.fn(),
  getExecutionOutput: vi.fn(),
  listDatasetRows: vi.fn(),
}));

const LABELS: Record<string, string> = {
  "channels.run.idle": "Idle",
  "channels.run.noUpstream": "No upstream",
  "channels.run.upstream": "Upstream outputs",
  "channels.run.result": "This node's result",
  "channels.run.running": "Running",
  "channels.run.empty": "No upstream output",
  "channels.run.absent": "Absent",
  "channels.run.outputFailed": "Output failed",
  "channels.run.notRecorded": "Not recorded",
  "channels.run.upstreamFailed": "Failed",
  "channels.run.skipped": "Skipped",
  "channels.run.otherUpstream": "Other available upstream",
  "channels.run.roundBadge": "Round {{n}}",
  "channels.template.focusRequired": "Focus a template field to insert a path.",
  "channels.run.target.draft": "Draft run",
  "channels.run.target.published": "Published run",
  "channels.run.startedAt": "Started {{time}}",
  "channels.run.stoppedAtThis": "Stops here",
  "channels.run.notStoppedHere": "Does not stop here",
  "channels.run.configChanged": "Configuration changed",
  "channels.run.sampleLoading": "Loading sample",
  "channels.run.round": "Round {{n}} / {{total}}",
  "channels.run.roundEmpty": "No rounds",
  "channels.run.roundPrevious": "Previous round",
  "channels.run.roundNext": "Next round",
  "channels.run.roundGo": "Go to round",
  "channels.run.roundFirstFailed": "First failed round",
  "channels.run.roundNoneFailed": "No failed round",
  "channels.run.roundLookupFailed": "The rounds could not be loaded",
  "channels.view.metric.total": "Total",
  "channels.view.metric.batch_size": "Batch size",
  "channels.run.showingRows": "Showing {{shown}} / {{total}}",
  "channels.run.batchRowCount": "{{count}} rows",
  "channels.view.metric.count": "Count",
  "channels.view.metric.index": "Index",
  "channels.view.nested": "Nested",
  "channels.editor.status.succeeded": "Succeeded",
  "problems.CHANNEL_NODE_FAILED": "Node failed",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
}));

const rowsView: OutputView = { kind: "rows", rows: "rows", metrics: ["count"] };
const recordView: OutputView = { kind: "record", metrics: [] };
const forView: OutputView = { kind: "container", item: "current", metrics: ["count"] };
const batchView: OutputView = {
  kind: "container",
  item: "rows",
  metrics: ["count", "total", "batch_size"],
};

const catalog: NodeTypeSpec[] = [
  {
    type: "read.sql",
    family: "read",
    label: "SQL",
    summary: "Reads",
    description: "",
    trigger: false,
    inputs: [],
    outputs: [],
    config_schema: {},
    permission: null,
    output_view: rowsView,
  },
  {
    type: "transform.set_fields",
    family: "transform",
    label: "Set",
    summary: "Sets",
    description: "",
    trigger: false,
    inputs: [],
    outputs: [],
    config_schema: {},
    permission: null,
    output_view: recordView,
  },
  {
    type: "volume.for",
    family: "volume",
    label: "For",
    summary: "Loops",
    description: "",
    trigger: false,
    inputs: [],
    outputs: [],
    config_schema: {},
    permission: null,
    output_view: forView,
  },
  {
    type: "volume.batch_read",
    family: "volume",
    label: "Batch",
    summary: "Batches",
    description: "",
    trigger: false,
    inputs: [],
    outputs: [],
    config_schema: {},
    permission: null,
    output_view: batchView,
  },
];

function detail(status: string): ChannelRunDetail {
  return {
    run: { status, stop_at_node_id: "b", job_id: "job_1", target: "draft", started_at: null },
    graph: EMPTY_GRAPH,
    node_summaries: [],
  } as unknown as ChannelRunDetail;
}

function sample(overrides: Partial<NodeSample> = {}): NodeSample {
  return {
    scope: [],
    config_changed: false,
    upstream: [],
    node: {
      state: "ok",
      seq: 5,
      status: "succeeded",
      output: { code: "S-01" },
      output_truncated: false,
      totals: {},
      input: null,
      input_totals: null,
      error: null,
      preview_only: false,
    },
    ...overrides,
  };
}

function upstream(overrides: Partial<NodeSampleUpstream> = {}): NodeSampleUpstream {
  return {
    node_id: "a",
    ref: "read",
    name: "Read",
    type_id: "read.sql",
    referenced: true,
    state: "ok",
    source: "execution",
    seq: 1,
    value: { rows: [{ code: "S-01" }], count: 1 },
    truncated: false,
    totals: { rows: 1 },
    error: null,
    preview_only: false,
    ...overrides,
  };
}

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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("node run regions", () => {
  it("shows idle copy without a run", () => {
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: null,
        nodeId: "b",
        nodeType: "transform.set_fields",
        nodes: [],
        detail: null,
        sample: null,
        loading: false,
        failure: null,
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("says the node has not executed when the sample has no execution", () => {
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "b",
        nodeType: "transform.set_fields",
        nodes: [],
        detail: detail("failed"),
        sample: sample({ node: { ...sample().node, state: "not_recorded", output: null } }),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByText("Absent")).toBeTruthy();
  });

  it("shows the node executing without an execution list", () => {
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "b",
        nodeType: "transform.set_fields",
        nodes: [],
        detail: detail("running"),
        sample: sample({ node: { ...sample().node, state: "running", output: null } }),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.queryByText(/Execution/)).toBeNull();
  });

  it("shows a failed result's error and its stored output", () => {
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "b",
        nodeType: "transform.set_fields",
        nodes: [],
        detail: detail("failed"),
        sample: sample({
          node: {
            ...sample().node,
            state: "failed",
            output: { code: "kept" },
            error: { code: "CHANNEL_NODE_FAILED", message: "write refused" },
          },
        }),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Node failed")).toBeTruthy();
    expect(screen.getByText("write refused")).toBeTruthy();
    expect(screen.getByRole("button", { name: "code" })).toBeTruthy();
    expect(screen.getByText("kept")).toBeTruthy();
  });

  it("expands referenced upstream and collapses the rest", () => {
    const onPick = vi.fn();
    const onOpenNode = vi.fn();
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        hasUpstream: true,
        detail: detail("succeeded"),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        roundOf: (id) => (id === "loop" ? 2 : 0),
        onOpenNode,
        onPick,
        sample: sample({
          scope: [{ container_node_id: "loop", container_seq: 4, round: 2, rounds_total: 5 }],
          upstream: [
            upstream(),
            upstream({
              node_id: "loop",
              ref: "walk",
              name: "Walk",
              type_id: "volume.for",
              referenced: false,
              source: "round_step",
              seq: null,
              value: { current: { code: "S-09" }, index: 2, count: 5 },
              totals: {},
            }),
            upstream({
              node_id: "other",
              ref: "other",
              name: "Other",
              type_id: "read.sql",
              referenced: false,
              value: { rows: [{ code: "hidden-other" }], count: 1 },
            }),
          ],
        }),
      }),
    );
    expect(screen.getByText("self.read.output")).toBeTruthy();
    expect(screen.getByText("S-01")).toBeTruthy();
    const other = screen.getByText("Other available upstream").closest("details");
    expect(other?.open).toBe(false);
    expect(other?.textContent).toContain("hidden-other");
    expect(screen.getByText("S-01").closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Round 3" }));
    expect(onOpenNode).toHaveBeenCalledWith("loop");
    expect(screen.getByText("Index")).toBeTruthy();
    const walk = screen.getByText("Walk").closest(".channel-upstream-entry");
    if (!(walk instanceof HTMLElement)) throw new Error("missing walk entry");
    expect(within(walk).getByRole("button", { name: "code" })).toBeTruthy();
    const read = screen.getByText("self.read.output").closest(".channel-upstream-entry");
    if (!(read instanceof HTMLElement)) throw new Error("missing read entry");
    fireEvent.click(within(read).getByRole("button", { name: "S-01" }));
    expect(onPick).toHaveBeenCalledWith(["rows", 0, "code"]);
  });

  it("inserts an upstream path only after a template field has focus", () => {
    const onInsert = vi.fn();
    const props = {
      channelId: "chn_1",
      jobId: "job_1",
      hasUpstream: true,
      detail: detail("succeeded"),
      loading: false,
      failure: null,
      catalog,
      ports: [],
      roundOf: () => 0,
      onInsert,
      sample: sample({ upstream: [upstream()] }),
    };
    mount(createElement(UpstreamRegion, { ...props, insertReady: false }));
    expect(screen.getByText("Focus a template field to insert a path.")).toBeTruthy();
    const idle = screen.getByRole("button", { name: "S-01" });
    expect((idle as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(idle);
    expect(onInsert).not.toHaveBeenCalled();

    cleanup();
    mount(createElement(UpstreamRegion, { ...props, insertReady: true }));
    expect(screen.queryByText("Focus a template field to insert a path.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "S-01" }));
    expect(onInsert).toHaveBeenCalledWith("read", ["rows", 0, "code"]);
  });

  it("keeps picks disabled when the upstream node has no ref", () => {
    const onInsert = vi.fn();
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        hasUpstream: true,
        detail: detail("succeeded"),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        roundOf: () => 0,
        onInsert,
        insertReady: true,
        sample: sample({ upstream: [upstream({ ref: "" })] }),
      }),
    );
    const cell = screen.getByRole("button", { name: "S-01" });
    expect((cell as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(cell);
    expect(onInsert).not.toHaveBeenCalled();
  });

  it("leaves the batch row expander enabled while insert picks stay disabled", async () => {
    const batch = catalog.find((item) => item.type === "volume.batch_read");
    if (!batch) throw new Error("missing batch type");
    vi.mocked(listRounds).mockResolvedValue({
      items: [
        {
          round: 1,
          step_preview: { rows: [{ code: "S-01" }], index: 1, count: 3, total: 2500 },
          step_truncated: false,
          step_totals: { rows: 1000 },
          status_counts: { succeeded: 1 },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    const props = {
      channelId: "chn_1",
      jobId: "job_1",
      hasUpstream: true,
      detail: detail("succeeded"),
      loading: false,
      failure: null,
      // Execution volume.batch_read is metrics only, so it never mounts this round table.
      catalog: [{ ...batch, type: "volume.batch_rounds" }],
      ports: [],
      roundOf: () => 0,
      onInsert: vi.fn(),
      sample: sample({
        upstream: [
          upstream({
            node_id: "batch",
            ref: "batches",
            name: "Batches",
            type_id: "volume.batch_rounds",
            source: "execution",
            seq: 4,
            value: { count: 3, total: 2500, batch_size: 1000 },
            totals: {},
          }),
        ],
      }),
    };
    const view = (ready: boolean) =>
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(UpstreamRegion, { ...props, insertReady: ready }),
      );
    const { rerender } = render(view(false));
    const expander = await screen.findByRole("button", { name: "1000 rows" });
    expect((expander as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "_ord" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(expander);
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "S-01" }) as HTMLButtonElement).disabled).toBe(true);
    });
    expect((screen.getByRole("button", { name: "1000 rows" }) as HTMLButtonElement).disabled).toBe(false);

    rerender(view(true));
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "S-01" }) as HTMLButtonElement).disabled).toBe(false);
    });
    expect((screen.getByRole("button", { name: "_ord" }) as HTMLButtonElement).disabled).toBe(false);
    vi.mocked(listRounds).mockImplementation(() =>
      Promise.resolve({ items: [], total: 0, limit: 50, offset: 0 }),
    );
  });

  it("names an upstream that was not recorded or failed, and keeps an error on an ok value", () => {
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        hasUpstream: true,
        detail: detail("succeeded"),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        roundOf: () => 0,
        sample: sample({
          upstream: [
            upstream({ node_id: "missing", name: "Missing", state: "not_recorded", value: null }),
            upstream({
              node_id: "bad",
              ref: "bad",
              name: "Bad",
              state: "failed",
              value: { rows: [{ code: "partial" }], count: 0 },
              error: { code: "CHANNEL_NODE_FAILED", message: "broke" },
            }),
            upstream({
              node_id: "skip",
              ref: "skip",
              name: "Skip",
              state: "ok",
              value: { rows: [{ code: "kept" }], count: 1 },
              error: { code: "CHANNEL_NODE_FAILED", message: "skipped downstream" },
            }),
          ],
        }),
      }),
    );
    expect(screen.getByText("Not recorded")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("broke")).toBeTruthy();
    expect(screen.getByText("partial")).toBeTruthy();
    expect(screen.getByText("skipped downstream")).toBeTruthy();
    expect(screen.getByText("kept")).toBeTruthy();
  });

  it("reports a node with no upstream before any run", () => {
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        jobId: null,
        hasUpstream: false,
        detail: null,
        sample: null,
        loading: false,
        failure: null,
        catalog,
        ports: [],
        roundOf: () => 0,
      }),
    );
    expect(screen.getByText("No upstream")).toBeTruthy();
    expect(screen.queryByText("Idle")).toBeNull();
  });

  it("shows idle copy for a node with upstream before any run", () => {
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        jobId: null,
        hasUpstream: true,
        detail: null,
        sample: null,
        loading: false,
        failure: null,
        catalog,
        ports: [],
        roundOf: () => 0,
      }),
    );
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("shows a load failure instead of an empty result", () => {
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "b",
        nodeType: "transform.set_fields",
        nodes: [],
        detail: detail("succeeded"),
        sample: null,
        loading: false,
        failure: new Error("down"),
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByText("Output failed")).toBeTruthy();
    expect(screen.queryByText("Absent")).toBeNull();
  });

  it("keeps the previous result when a later sample fails", () => {
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "b",
        nodeType: "transform.set_fields",
        nodes: [],
        detail: detail("succeeded"),
        sample: sample({
          node: { ...sample().node, state: "ok", output: { code: "kept" } },
        }),
        loading: false,
        failure: new Error("down"),
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByRole("alert").textContent).toBe("Output failed");
    expect(screen.getByText("kept")).toBeTruthy();
  });

  it("does not page a preview-only rows result", () => {
    const rows = Array.from({ length: 100 }, (_, index) => ({ code: `S-${index}` }));
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "b",
        nodeType: "read.sql",
        nodes: [],
        detail: detail("succeeded"),
        sample: sample({
          node: {
            ...sample().node,
            seq: 8,
            output: { rows, count: 250 },
            output_truncated: true,
            totals: { rows: 250 },
            preview_only: true,
          },
        }),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    expect(screen.getByText("Showing 100 / 250")).toBeTruthy();
    const next = screen.queryByRole("button", { name: "2" });
    if (next) fireEvent.click(next);
    expect(getExecutionOutput).not.toHaveBeenCalled();
  });

  it("renders a finished Batch Read upstream as metrics and the node's own result as rounds", async () => {
    const output = { count: 3, total: 2500, batch_size: 1000 };
    mount(
      createElement(UpstreamRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        hasUpstream: true,
        detail: detail("succeeded"),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        roundOf: () => 0,
        sample: sample({
          upstream: [
            upstream({
              node_id: "batch",
              ref: "batches",
              name: "Batches",
              type_id: "volume.batch_read",
              source: "execution",
              seq: 4,
              value: output,
              totals: {},
            }),
          ],
        }),
      }),
    );
    expect(screen.getByText("Count")).toBeTruthy();
    expect(screen.getByText("Total")).toBeTruthy();
    expect(screen.getByText("Batch size")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(listRounds).not.toHaveBeenCalled();
    cleanup();
    mount(
      createElement(ResultRegion, {
        channelId: "chn_1",
        jobId: "job_1",
        nodeId: "batch",
        nodeType: "volume.batch_read",
        nodes: [],
        detail: detail("succeeded"),
        sample: sample({
          node: { ...sample().node, seq: 9, output },
        }),
        loading: false,
        failure: null,
        catalog,
        ports: [],
        graph: null,
        selectedRound: null,
        onRound: vi.fn(),
        onRoundsTotal: vi.fn(),
      }),
    );
    await waitFor(() =>
      expect(listRounds).toHaveBeenCalledWith("chn_1", "job_1", 9, { limit: 50, offset: 0 }),
    );
  });
});

describe("sample bar", () => {
  const run = {
    target: "draft" as const,
    started_at: null,
    stop_at_node_id: "b",
  };
  const nodes = [
    { id: "loop", name: "Walk", ref: "walk", type: "volume.for" },
    { id: "b", name: "Write", ref: "write", type: "write.entity", parent: "loop" },
  ];

  it("names the run and hides the round control outside a container", () => {
    mount(
      createElement(SampleBar, {
        run,
        nodeId: "plain",
        nodes: [{ id: "plain", name: "Plain", ref: "plain", type: "transform.set_fields" }],
        sample: sample({ config_changed: true }),
        loading: true,
        channelId: "chn_1",
        jobId: "job_1",
        roundOf: () => 0,
        totalOf: () => 0,
        onRound: vi.fn(),
      }),
    );
    expect(screen.getByText("Draft run")).toBeTruthy();
    expect(screen.getByText("Does not stop here")).toBeTruthy();
    expect(screen.getByText("Configuration changed")).toBeTruthy();
    expect(screen.getByText("Loading sample")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Previous round" })).toBeNull();
  });

  it("counts rounds from 1 and sends a zero-based round", async () => {
    const onRound = vi.fn();
    vi.mocked(listRounds).mockResolvedValue({
      items: [
        { round: 0, step_preview: {}, step_truncated: false, step_totals: {}, status_counts: { succeeded: 1 } },
        { round: 1, step_preview: {}, step_truncated: false, step_totals: {}, status_counts: { failed: 1 } },
      ],
      total: 5,
      limit: 200,
      offset: 0,
    });
    mount(
      createElement(SampleBar, {
        run: { ...run, stop_at_node_id: "loop", target: "published" },
        nodeId: "loop",
        nodes,
        sample: sample(),
        loading: false,
        channelId: "chn_1",
        jobId: "job_1",
        roundOf: () => 0,
        totalOf: () => 5,
        onRound,
      }),
    );
    expect(screen.getByText("Published run")).toBeTruthy();
    expect(screen.getByText("Stops here")).toBeTruthy();
    expect(screen.getByText("Round 1 / 5")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous round" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Next round" }));
    expect(onRound).toHaveBeenCalledWith("loop", 1);
    fireEvent.change(screen.getByRole("spinbutton", { name: "Go to round" }), { target: { value: "4" } });
    fireEvent.submit(screen.getByRole("spinbutton", { name: "Go to round" }).closest("form") as HTMLFormElement);
    expect(onRound).toHaveBeenCalledWith("loop", 3);
    fireEvent.click(screen.getByRole("button", { name: "First failed round" }));
    await waitFor(() => expect(onRound).toHaveBeenCalledWith("loop", 1));
  });

  it("shows a sentence when the failed-round lookup is rejected", async () => {
    vi.mocked(listRounds).mockRejectedValueOnce(new Error("down"));
    const onRound = vi.fn();
    mount(
      createElement(SampleBar, {
        run: { ...run, stop_at_node_id: "loop" },
        nodeId: "loop",
        nodes,
        sample: sample(),
        loading: false,
        channelId: "chn_1",
        jobId: "job_1",
        roundOf: () => 0,
        totalOf: () => 5,
        onRound,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "First failed round" }));
    expect(await screen.findByText("The rounds could not be loaded")).toBeTruthy();
    expect(onRound).not.toHaveBeenCalled();
  });
});

describe("useNodeSample", () => {
  const ready = sample({ node: { ...sample().node, output: { first: true } } });
  const later = sample({ node: { ...sample().node, output: { second: true } } });

  it("debounces a graph edit, keeps the previous sample, and drops a stale response", async () => {
    vi.useFakeTimers();
    try {
      let resolveFirst: (value: NodeSample) => void = () => undefined;
      let resolveSecond: (value: NodeSample) => void = () => undefined;
      let resolveThird: (value: NodeSample) => void = () => undefined;
      vi.mocked(nodeSample)
        .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
        .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }))
        .mockImplementationOnce(() => new Promise((resolve) => { resolveThird = resolve; }));
      const graph = EMPTY_GRAPH;
      const edited = {
        ...EMPTY_GRAPH,
        nodes: [
          {
            id: "n",
            ref: "n",
            type: "transform.set_fields",
            name: "N",
            position: { x: 1, y: 1 },
            config: { touched: true },
            on_error: "stop" as const,
            retry: null,
          },
        ],
      };
      const { result, rerender } = renderHook(
        (props: { graph: Graph; scope?: { container_node_id: string; round: number }[] }) =>
          useNodeSample({
            channelId: "chn_1",
            jobId: "job_1",
            nodeId: "b",
            graph: props.graph,
            scope: props.scope,
            enabled: true,
          }),
        { initialProps: { graph, scope: undefined as { container_node_id: string; round: number }[] | undefined } },
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(nodeSample).toHaveBeenCalledTimes(1);
      await act(async () => {
        resolveFirst(ready);
        await Promise.resolve();
      });
      expect(result.current.sample?.node.output).toEqual({ first: true });

      rerender({ graph: edited, scope: undefined });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(399);
      });
      expect(nodeSample).toHaveBeenCalledTimes(1);
      expect(result.current.loading).toBe(true);
      expect(result.current.sample?.node.output).toEqual({ first: true });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(nodeSample).toHaveBeenCalledTimes(2);

      rerender({ graph: edited, scope: [{ container_node_id: "loop", round: 1 }] });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(nodeSample).toHaveBeenCalledTimes(3);
      await act(async () => {
        resolveSecond(sample({ node: { ...sample().node, output: { stale: true } } }));
        await Promise.resolve();
      });
      expect(result.current.sample?.node.output).toEqual({ first: true });
      await act(async () => {
        resolveThird(later);
        await Promise.resolve();
      });
      expect(result.current.sample?.node.output).toEqual({ second: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("refetches immediately when the recorded key changes and keeps the previous sample", async () => {
    vi.useFakeTimers();
    try {
      let resolveFirst: (value: NodeSample) => void = () => undefined;
      let resolveSecond: (value: NodeSample) => void = () => undefined;
      vi.mocked(nodeSample)
        .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
        .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
      const { result, rerender } = renderHook(
        (props: { recordedKey: string }) =>
          useNodeSample({
            channelId: "chn_1",
            jobId: "job_1",
            nodeId: "b",
            graph: EMPTY_GRAPH,
            scope: undefined,
            recordedKey: props.recordedKey,
            enabled: true,
          }),
        { initialProps: { recordedKey: "job_1|running|b:1" } },
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        resolveFirst(ready);
        await Promise.resolve();
      });
      expect(result.current.sample?.node.output).toEqual({ first: true });
      expect(nodeSample).toHaveBeenCalledTimes(1);

      rerender({ recordedKey: "job_1|running|b:2" });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(nodeSample).toHaveBeenCalledTimes(2);
      expect(result.current.loading).toBe(true);
      expect(result.current.sample?.node.output).toEqual({ first: true });
      await act(async () => {
        resolveSecond(later);
        await Promise.resolve();
      });
      expect(result.current.sample?.node.output).toEqual({ second: true });
      expect(result.current.loading).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears a failure when the node changes", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(nodeSample)
        .mockRejectedValueOnce(new Error("down"))
        .mockImplementationOnce(() => new Promise(() => undefined));
      const { result, rerender } = renderHook(
        (props: { nodeId: string }) =>
          useNodeSample({
            channelId: "chn_1",
            jobId: "job_1",
            nodeId: props.nodeId,
            graph: EMPTY_GRAPH,
            scope: undefined,
            enabled: true,
          }),
        { initialProps: { nodeId: "a" } },
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.failure).toBeInstanceOf(Error);
      expect(result.current.sample).toBeNull();
      rerender({ nodeId: "b" });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.failure).toBeNull();
      expect(result.current.sample).toBeNull();
      expect(result.current.loading).toBe(true);
      expect(nodeSample).toHaveBeenLastCalledWith("chn_1", "job_1", {
        graph: EMPTY_GRAPH,
        node_id: "b",
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
