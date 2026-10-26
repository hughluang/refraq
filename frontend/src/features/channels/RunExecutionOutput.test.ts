/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { getExecutionOutput, listDatasetRows, listExecutions, listRounds, previewTemplate } from "@/features/channels/api";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import { EMPTY_GRAPH, type Graph, type NodeExecution, type OutputView } from "@/features/channels/types";
import { ApiError } from "@/lib/api";
import { copyText } from "@/lib/copy-text";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template =
      ({
        "channels.run.showFullOutput": "Show full output",
        "channels.run.outputFailed": "Output failed",
        "channels.run.previewOnly": "This execution stored a preview.",
        "channels.run.previewTotal": "{{path}} total {{count}}",
        "channels.run.dataset.reference": "Dataset reference",
        "channels.run.dataset.count": "{{count}} rows",
        "channels.run.dataset.showRows": "Show rows",
        "channels.run.dataset.round": "Batch {{index}}",
        "common.showing": "{{from}}-{{to}} of {{total}}",
        "channels.run.dataset.reason.expired": "This dataset has expired",
        "channels.run.rowsFailed": "The rows could not be loaded",
        "channels.run.showingRows": "Showing {{shown}} / {{total}}",
        "channels.run.column.value": "Value",
        "channels.run.column.until": "until",
        "channels.run.column.round": "#",
        "channels.run.roundStatus": "Status",
        "channels.run.ordRange": "{{from}}–{{to}}",
        "channels.run.batchRowCount": "{{count}} rows",
        "channels.run.copyDatasetId": "Copy dataset id {{id}}",
        "channels.run.notRecorded": "Not recorded",
        "channels.view.nested": "Nested",
        "channels.view.metric.count": "Count",
        "channels.view.metric.inserted": "Inserted",
        "channels.view.metric.updated": "Updated",
        "channels.view.metric.unchanged": "Unchanged",
        "channels.view.metric.deleted": "Deleted",
        "channels.view.metric.unmatched": "Unmatched",
        "channels.view.metric.index": "Index",
        "channels.editor.status.succeeded": "Succeeded",
        "channels.editor.status.failed": "Failed",
        "problems.CHANNEL_NODE_FAILED": "Node failed",
        "problems.CHANNEL_VALUE_TYPE_MISMATCH": "Type mismatch",
      })[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
}));

vi.mock("@/features/channels/api", () => ({
  getExecutionOutput: vi.fn(),
  listDatasetRows: vi.fn(),
  listRounds: vi.fn(),
  listExecutions: vi.fn(),
  previewTemplate: vi.fn(),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: vi.fn(() => Promise.resolve()),
}));

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

function mount(node: ReturnType<typeof createElement>) {
  render(createElement(MantineProvider, { env: "test" }, node));
}

function roundCell(round: number, column: number): HTMLElement {
  const cell = document.querySelector(`[data-round='${round}']`)?.querySelectorAll("td")[column];
  if (!cell) throw new Error(`missing cell ${round}:${column}`);
  return cell;
}

function untilCell(round: number): HTMLElement {
  return roundCell(round, 2);
}

function statusCell(round: number): HTMLElement {
  return roundCell(round, 3);
}

const rowsView: OutputView = { kind: "rows", rows: "rows", metrics: ["count"] };
const recordView: OutputView = { kind: "record", metrics: [] };
const countsView: OutputView = {
  kind: "counts",
  metrics: ["inserted", "updated", "unchanged", "deleted", "unmatched"],
};
const datasetView: OutputView = { kind: "dataset", dataset: "dataset", metrics: ["count"] };
const forView: OutputView = { kind: "container", item: "current", metrics: ["count"] };
const untilView: OutputView = { kind: "container", item: "index", metrics: ["count"] };
const batchView: OutputView = {
  kind: "container",
  item: "rows",
  metrics: ["count", "total", "batch_size"],
};

it("renders a record as a collapsed key tree and reports each key path", () => {
  const onPick = vi.fn();
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: recordView,
      value: { code: "S-01", address: { city: "Paris" } },
      onPick,
    }),
  );
  const nested = screen.getByText("city").closest("details");
  expect(nested?.open).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "code" }));
  fireEvent.click(screen.getByRole("button", { name: "address" }));
  fireEvent.click(nested?.querySelector("summary") as HTMLElement);
  fireEvent.click(screen.getByRole("button", { name: "city" }));
  expect(onPick.mock.calls.map((call) => call[0])).toEqual([
    ["code"],
    ["address"],
    ["address", "city"],
  ]);
});

it("pages a rows table by path and picks the list path from a column header", async () => {
  const onPick = vi.fn();
  const embedded = Array.from({ length: 100 }, (_, index) => ({ code: `S-${index}`, extra: `x-${index}` }));
  vi.mocked(getExecutionOutput).mockResolvedValue({
    items: [{ code: "S-100", extra: 100 }],
    total: 150,
    limit: 100,
    offset: 100,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: rowsView,
      value: { rows: embedded, count: 150 },
      totals: { rows: 150 },
      truncated: true,
      seq: 4,
      rowProperties: ["code", "name"],
      onPick,
    }),
  );
  expect(screen.getByText("Showing 100 / 150")).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "code" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "name" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "extra" })).toBeTruthy();
  expect(screen.getByText("Count")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "code" }));
  fireEvent.click(screen.getByRole("button", { name: "S-0" }));
  expect(onPick).toHaveBeenCalledWith(["rows"]);
  expect(onPick).toHaveBeenCalledWith(["rows", 0, "code"]);
  expect(getExecutionOutput).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  await waitFor(() => expect(screen.getByText("S-100")).toBeTruthy());
  expect(getExecutionOutput).toHaveBeenCalledWith("chn_1", "job_1", 4, {
    path: "rows",
    limit: 100,
    offset: 100,
  });
});

it("does not page a preview-only rows execution", () => {
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: rowsView,
      value: { rows: [{ code: "S-01" }], count: 1000000 },
      totals: { rows: 1000000 },
      truncated: true,
      previewOnly: true,
      seq: 8,
    }),
  );
  expect(screen.getByText("This execution stored a preview.")).toBeTruthy();
  expect(screen.getByText("rows total 1000000")).toBeTruthy();
  expect(screen.getByText("Showing 1 / 1000000")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "2" })).toBeNull();
  expect(getExecutionOutput).not.toHaveBeenCalled();
});

it("shows a dataset without the storage ordinal and pages its rows", async () => {
  const onPick = vi.fn();
  vi.mocked(listDatasetRows)
    .mockResolvedValueOnce({
      items: [{ _ord: 1, code: "S-01" }],
      limit: 200,
      next_after_ord: 1,
    })
    .mockResolvedValueOnce({
      items: [{ _ord: 201, code: "S-03" }],
      limit: 50,
      next_after_ord: null,
    });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: datasetView,
      value: {
        dataset: {
          dataset_id: "dst_1",
          columns: [{ name: "code", type: "string" }],
          count: 250,
        },
        count: 250,
      },
      onPick,
    }),
  );
  expect(screen.getByText("code (string)")).toBeTruthy();
  expect(screen.getByText("250 rows")).toBeTruthy();
  expect(screen.queryByRole("columnheader", { name: "_ord" })).toBeNull();
  await waitFor(() => expect(screen.getByText("S-01")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "Copy dataset id dst_1" }));
  expect(onPick).toHaveBeenCalledWith(["dataset", "dataset_id"]);
  fireEvent.click(screen.getByRole("button", { name: "code" }));
  expect(onPick).toHaveBeenCalledWith(["dataset"]);
  expect(copyText).toHaveBeenCalledWith("dst_1");
  expect(listDatasetRows).toHaveBeenCalledWith("chn_1", "job_1", "dst_1", {
    after_ord: 0,
    limit: 200,
  });
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  await waitFor(() => expect(screen.getByText("S-03")).toBeTruthy());
  expect(getExecutionOutput).not.toHaveBeenCalled();
});

it("shows why a dataset cannot be read", async () => {
  vi.mocked(listDatasetRows).mockRejectedValue(
    new ApiError(404, "CHANNEL_DATASET_UNAVAILABLE", "Dataset is not available", null, {
      reason: "expired",
    }),
  );
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: datasetView,
      value: {
        dataset: {
          dataset_id: "dst_old",
          columns: [{ name: "code", type: "string" }],
          count: 4,
        },
        count: 4,
      },
    }),
  );
  await waitFor(() => expect(screen.getByText("This dataset has expired")).toBeTruthy());
  expect(screen.queryByText(/regenerat/i)).toBeNull();
});

it("shows a clipboard failure for the dataset id", async () => {
  vi.mocked(copyText).mockRejectedValueOnce(new Error("denied"));
  vi.mocked(listDatasetRows).mockResolvedValue({
    items: [{ _ord: 1, code: "S-01" }],
    limit: 200,
    next_after_ord: null,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: datasetView,
      value: {
        dataset: {
          dataset_id: "dst_1",
          columns: [{ name: "code", type: "string" }],
          count: 1,
        },
        count: 1,
      },
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Copy dataset id dst_1" }));
  expect((await screen.findByText("common.copy.failed")).textContent).toBe("common.copy.failed");
});

it("reports a rows page that is not a list and does not keep another page's rows", async () => {
  const embedded = [{ code: "E-0" }];
  let resolvePage: (value: { value: unknown }) => void = () => undefined;
  vi.mocked(getExecutionOutput).mockImplementation((_id, _job, _seq, params) => {
    if ((params?.offset ?? 0) === 0) {
      return Promise.resolve({
        items: [{ code: "FROM-TOTAL" }],
        total: 250,
        limit: 100,
        offset: 0,
      });
    }
    return new Promise((resolve) => {
      resolvePage = resolve;
    });
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: rowsView,
      value: { rows: embedded },
      truncated: true,
      seq: 4,
    }),
  );
  expect(await screen.findByText("Showing 1 / 250")).toBeTruthy();
  expect(screen.queryByText("FROM-TOTAL")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  expect(screen.queryByText("FROM-TOTAL")).toBeNull();
  expect(screen.queryByText("E-0")).toBeNull();
  resolvePage({ value: { nope: true } });
  expect(await screen.findByText("The rows could not be loaded")).toBeTruthy();
  expect(screen.queryByText("FROM-TOTAL")).toBeNull();
});

it("renders counts as labeled metrics and keeps a failed output beside its error", () => {
  const onPick = vi.fn();
  const item = {
    seq: 3,
    status: "failed",
    error_code: "CHANNEL_NODE_FAILED",
    error_message: "write refused",
    output_preview: { inserted: 1, updated: 0, unchanged: 0, deleted: 0, unmatched: 2 },
    output_truncated: false,
    preview_only: false,
    preview_totals: {},
  } as NodeExecution;
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      item,
      view: countsView,
      onPick,
    }),
  );
  expect(screen.getByText("Node failed")).toBeTruthy();
  expect(screen.getByText("write refused")).toBeTruthy();
  expect(screen.getByText("Inserted")).toBeTruthy();
  expect(screen.getByText("2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Unmatched/ }));
  expect(onPick).toHaveBeenCalledWith(["unmatched"]);
});

it("renders a value as JSON", () => {
  const onPick = vi.fn();
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: { kind: "value", metrics: [] },
      value: { ok: true },
      onPick,
    }),
  );
  expect(screen.getByText(/"ok": true/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /"ok": true/ }));
  expect(onPick).toHaveBeenCalledWith([]);
});

it("spreads a For round into columns, highlights a failed round, and selects that round", async () => {
  const onSelectRound = vi.fn();
  const onPick = vi.fn();
  vi.mocked(listRounds).mockResolvedValue({
    items: [
      {
        round: 0,
        step_preview: { current: { code: "S-01", name: "Ada" }, index: 0, count: 2 },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
      {
        round: 1,
        step_preview: { current: { code: "S-02" }, index: 1, count: 2 },
        step_truncated: false,
        step_totals: {},
        status_counts: { failed: 1 },
      },
    ],
    total: 2,
    limit: 50,
    offset: 0,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: forView,
      value: { count: 2, current: { code: "S-02" }, index: 1, iterations: [] },
      seq: 7,
      rowProperties: ["code", "name"],
      selectedRound: 1,
      onSelectRound,
      onPick,
    }),
  );
  expect(await screen.findByText("S-01")).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "name" })).toBeTruthy();
  const failed = document.querySelector("[data-round='1']");
  expect(failed?.getAttribute("data-failed")).toBe("true");
  expect(failed?.getAttribute("aria-selected")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "code" }));
  fireEvent.click(screen.getByText("S-01"));
  expect(onPick).toHaveBeenCalledWith(["current", "code"]);
  expect(onSelectRound).toHaveBeenCalledWith(0);
  expect(listRounds).toHaveBeenCalledWith("chn_1", "job_1", 7, { limit: 50, offset: 0 });
});

it("shows an Until round's index in the value column", async () => {
  const onPick = vi.fn();
  vi.mocked(listRounds).mockResolvedValue({
    items: [
      {
        round: 0,
        step_preview: { index: 0, until: { value: false } },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
      {
        round: 1,
        step_preview: { index: 1, until: { value: true } },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
    ],
    total: 2,
    limit: 50,
    offset: 0,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: untilView,
      value: { count: 2, index: 1, iterations: [] },
      seq: 4,
      onPick,
    }),
  );
  expect(await screen.findByRole("button", { name: "0" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "1" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "until" })).toBeTruthy();
  expect(screen.getByText("false")).toBeTruthy();
  expect(screen.getByText("true")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "0" }));
  expect(onPick).toHaveBeenCalledWith(["index"]);
});

it("localizes an Until condition failure by problem code and leaves values as text", async () => {
  vi.mocked(listRounds).mockResolvedValue({
    items: [
      {
        round: 0,
        step_preview: { index: 0, until: { value: false } },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
      {
        round: 1,
        step_preview: { index: 1, until: { value: true } },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
      {
        round: 2,
        step_preview: {
          index: 2,
          until: {
            error: {
              code: "CHANNEL_VALUE_TYPE_MISMATCH",
              message: "Value does not match the declared type",
            },
          },
        },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
      {
        round: 3,
        step_preview: {
          index: 3,
          until: { error: { code: "CHANNEL_NODE_FAILED", message: "Code failed at line 1" } },
        },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
      {
        round: 4,
        step_preview: { index: 4 },
        step_truncated: false,
        step_totals: {},
        status_counts: { failed: 1 },
      },
      {
        round: 5,
        step_preview: {
          index: 5,
          until: { error: { code: "CHANNEL_SANDBOX_FAILED", message: "Sandbox could not start" } },
        },
        step_truncated: false,
        step_totals: {},
        status_counts: { succeeded: 1 },
      },
    ],
    total: 6,
    limit: 50,
    offset: 0,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: untilView,
      value: { count: 1, index: 0, iterations: [] },
      seq: 4,
    }),
  );
  expect(await screen.findByText("false")).toBeTruthy();
  expect(untilCell(0).textContent).toBe("false");
  expect(untilCell(1).textContent).toBe("true");
  expect(untilCell(2).textContent).toBe("Type mismatchValue does not match the declared type");
  expect(screen.getByText("Value does not match the declared type").closest("td")).toBe(untilCell(2));
  expect(untilCell(3).textContent).toBe("Node failedCode failed at line 1");
  expect(untilCell(4).textContent).toBe("");
  expect(untilCell(5).textContent).toBe("Sandbox could not start");
  expect(statusCell(2).textContent).toBe("Succeeded 1");
});

it("shows a batch round's ordinal range and expands that batch through the row window", async () => {
  const graph: Graph = {
    ...EMPTY_GRAPH,
    nodes: [
      {
        id: "batch",
        ref: "batches",
        type: "volume.batch_read",
        name: "Batches",
        position: { x: 0, y: 0 },
        config: {},
        on_error: "stop",
        retry: null,
      },
      {
        id: "write",
        ref: "write",
        type: "write.entity",
        name: "Write",
        position: { x: 40, y: 40 },
        parent: "batch",
        config: {},
        on_error: "stop",
        retry: null,
      },
    ],
  };
  vi.mocked(listRounds).mockResolvedValue({
    items: [
      {
        round: 1,
        step_preview: { rows: [{ code: "preview" }], index: 1, count: 3, total: 2500 },
        step_truncated: true,
        step_totals: { rows: 1000 },
        status_counts: { succeeded: 1 },
      },
    ],
    total: 3,
    limit: 50,
    offset: 0,
  });
  vi.mocked(listExecutions).mockResolvedValue({
    items: [
      {
        seq: 4,
        node_id: "batch",
        output_preview: { count: 3, total: 2500, batch_size: 1000 },
      } as NodeExecution,
    ],
    total: 1,
    limit: 200,
    offset: 0,
  });
  vi.mocked(previewTemplate).mockResolvedValue({
    state: "ok",
    value: {
      dataset_id: "dst_1",
      columns: [{ name: "code", type: "string" }],
      count: 2500,
    },
    truncated: false,
  });
  vi.mocked(listDatasetRows).mockResolvedValue({
    items: [{ _ord: 1001, code: "S-01" }],
    limit: 200,
    next_after_ord: 1001,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: batchView,
      value: { count: 3, total: 2500, batch_size: 1000 },
      seq: 4,
      graph,
      containerId: "batch",
    }),
  );
  expect(await screen.findByText("1001–2000")).toBeTruthy();
  expect(screen.getByRole("button", { name: "1000 rows" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "1000 rows" }));
  expect(await screen.findByText("S-01")).toBeTruthy();
  expect(screen.queryByText("preview")).toBeNull();
  expect(previewTemplate).toHaveBeenCalledWith("chn_1", "job_1", {
    graph,
    node_id: "batch",
    path: ["dataset"],
  });
});

it("leaves the ordinal blank when the batch size or the step total is missing", async () => {
  vi.mocked(listRounds).mockResolvedValue({
    items: [
      {
        round: 1,
        step_preview: { rows: [{ code: "preview" }], index: 1, count: 3, total: 2500 },
        step_truncated: true,
        step_totals: { rows: 1000 },
        status_counts: {},
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: batchView,
      value: { count: 3 },
      seq: 4,
      graph: EMPTY_GRAPH,
      containerId: "batch",
    }),
  );
  expect(await screen.findByRole("button", { name: "1000 rows" })).toBeTruthy();
  expect(screen.queryByText("1001–2000")).toBeNull();

  cleanup();
  vi.mocked(listRounds).mockResolvedValue({
    items: [
      {
        round: 1,
        step_preview: { rows: [{ code: "preview" }], index: 1, count: 3 },
        step_truncated: true,
        step_totals: { rows: 1000 },
        status_counts: {},
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  });
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: batchView,
      value: { count: 3, total: 2500, batch_size: 1000 },
      seq: 4,
      graph: EMPTY_GRAPH,
      containerId: "batch",
    }),
  );
  expect(await screen.findByRole("button", { name: "1000 rows" })).toBeTruthy();
  expect(screen.queryByText("1001–2000")).toBeNull();
});

it("renders For iterations as one row per round and one column per body ref", () => {
  const onPick = vi.fn();
  mount(
    createElement(RunExecutionOutput, {
      channelId: "chn_1",
      jobId: "job_1",
      view: forView,
      iterations: true,
      value: {
        count: 2,
        iterations: [{ read: { code: "S-01" } }, { read: { code: "S-02" }, write: { inserted: 1 } }],
      },
      onPick,
    }),
  );
  expect(screen.getByText("Showing 2 / 2")).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "read" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "write" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "read" }));
  fireEvent.click(screen.getByRole("button", { name: /S-02/ }));
  expect(onPick).toHaveBeenCalledWith(["iterations"]);
  expect(onPick).toHaveBeenCalledWith(["iterations", 1, "read"]);
});
