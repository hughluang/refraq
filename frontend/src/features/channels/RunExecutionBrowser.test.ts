/** @vitest-environment jsdom */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { listDatasetRows, listExecutions, previewTemplate } from "@/features/channels/api";
import { RunExecutionBrowser } from "@/features/channels/RunExecutionBrowser";
import { EMPTY_GRAPH, type Graph, type NodeExecution } from "@/features/channels/types";
import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { bindClientI18n } from "@/providers/i18n-runtime";
import { ConsoleNotifications } from "@/providers/notification-provider";

vi.mock("@refinedev/core", () => ({
  useNotification: () => ({ open: vi.fn() }),
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template =
      ({
        "channels.run.executionList": "Executions",
        "channels.run.dataset.round": "Batch {{index}}",
        "channels.run.dataset.reference": "Dataset reference",
        "channels.run.dataset.count": "{{count}} rows",
        "channels.run.dataset.showRows": "Show rows",
        "channels.run.previewOnly": "This execution stored a preview.",
        "channels.run.previewTotal": "{{path}} total {{count}}",
        "common.showing": "{{from}}-{{to}} of {{total}}",
      })[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
}));

vi.mock("@/features/channels/api", () => ({
  listExecutions: vi.fn(),
  listDatasetRows: vi.fn(),
  previewTemplate: vi.fn(),
  getExecutionOutput: vi.fn(),
}));

const reference = {
  dataset_id: "dst_1",
  columns: [{ name: "code", type: "string" }],
  count: 2500,
};

function execution(overrides: Record<string, unknown>): NodeExecution {
  return {
    seq: 1,
    node_id: "write",
    container_seq: null,
    round: null,
    status: "succeeded",
    started_at: null,
    finished_at: null,
    output_bytes: 0,
    output_preview: null,
    output_truncated: false,
    preview_only: false,
    preview_totals: {},
    error_code: null,
    error_message: null,
    error_detail: null,
    ...overrides,
  } as NodeExecution;
}

const graph: Graph = {
  ...EMPTY_GRAPH,
  nodes: [
    {
      id: "batch",
      ref: "batches",
      type: "volume.batch_read",
      name: "Batches",
      position: { x: 0, y: 0 },
      config: { batch_size: 1000 },
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

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, createElement(ConsoleNotifications), node);
}

afterEach(() => {
  cleanup();
  resetNotifications();
  bindClientI18n({ t: (key: string) => key } as never);
  vi.clearAllMocks();
});

it("pages executions and loads one batch round through the row window", async () => {
  const child = execution({
    seq: 9,
    node_id: "write",
    container_seq: 4,
    round: 1,
    preview_only: true,
    preview_totals: { rows: 1000 },
    output_preview: { inserted: 1 },
  });
  const later = execution({ seq: 60, node_id: "write", round: 2, container_seq: 4 });
  const container = execution({
    seq: 4,
    node_id: "batch",
    output_preview: { count: 3, total: 2500, batch_size: 1000 },
  });
  vi.mocked(listExecutions).mockImplementation(async (_channelId, _jobId, params) => {
    if (params?.node_id === "batch") {
      return { items: [container], total: 1, limit: 200, offset: 0 };
    }
    if (params?.offset === 50) {
      return { items: [later], total: 51, limit: 50, offset: 50 };
    }
    return { items: [child], total: 51, limit: 50, offset: 0 };
  });
  vi.mocked(previewTemplate).mockResolvedValue({
    state: "ok",
    value: reference,
    truncated: false,
  });
  vi.mocked(listDatasetRows).mockResolvedValue({
    items: [
      { _ord: 1001, code: "S-01" },
      { _ord: 2001, code: "past" },
    ],
    limit: 200,
    next_after_ord: 2001,
  });

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph }),
    ),
  );

  expect(await screen.findByRole("button", { name: "Write" })).toBeTruthy();
  expect(listExecutions).toHaveBeenCalledWith("chn_1", "job_1", { limit: 50, offset: 0 });
  fireEvent.click(screen.getByRole("button", { name: "Write" }));
  expect(await screen.findByText("This execution stored a preview.")).toBeTruthy();
  expect(screen.getByText("rows total 1000")).toBeTruthy();
  expect(await screen.findByText("S-01")).toBeTruthy();
  expect(screen.queryByText("past")).toBeNull();
  expect(listDatasetRows).toHaveBeenCalledWith("chn_1", "job_1", "dst_1", {
    after_ord: 1000,
    limit: 200,
  });
  expect(previewTemplate).toHaveBeenCalledWith("chn_1", "job_1", {
    graph,
    node_id: "batch",
    path: ["dataset"],
  });
  fireEvent.click(screen.getAllByRole("button", { name: "2" })[0]);
  await waitFor(() => {
    expect(listExecutions).toHaveBeenCalledWith("chn_1", "job_1", { limit: 50, offset: 50 });
  });
});

it("shows unloaded and one notification when the first execution load fails", async () => {
  bindClientI18n({
    t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
  } as never);
  vi.mocked(listExecutions).mockRejectedValue(
    new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-exec"),
  );
  render(shell(createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph })));

  expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
  expect(screen.queryByText("channels.run.outputFailed")).toBeNull();
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.getByText("problems.unknown")).toBeTruthy();
  expect(screen.getByRole("button", { name: "common.retry" })).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  await waitFor(() => expect(listExecutions).toHaveBeenCalledTimes(2));
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.getByText("problems.unknown Repeated 2 times")).toBeTruthy();
});

it("reloads the current execution page when the parent reload token changes and keeps the page", async () => {
  const pageOne = execution({ seq: 9, node_id: "write", status: "succeeded" });
  const pageTwo = execution({ seq: 60, node_id: "write", status: "succeeded" });
  const pageTwoNext = execution({ seq: 60, node_id: "write", status: "running" });
  let pageTwoLoads = 0;
  vi.mocked(listExecutions).mockImplementation(async (_channelId, _jobId, params) => {
    if (params?.offset === 50) {
      pageTwoLoads += 1;
      return {
        items: [pageTwoLoads > 1 ? pageTwoNext : pageTwo],
        total: 51,
        limit: 50,
        offset: 50,
      };
    }
    return { items: [pageOne], total: 51, limit: 50, offset: 0 };
  });
  const view = render(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 0,
      }),
    ),
  );

  expect(await screen.findByText("channels.editor.status.succeeded")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  expect(await screen.findByText("51-51 of 51")).toBeTruthy();
  view.rerender(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 1,
      }),
    ),
  );

  expect(await screen.findByText("channels.editor.status.running")).toBeTruthy();
  expect(screen.getByText("51-51 of 51")).toBeTruthy();
  expect(vi.mocked(listExecutions).mock.calls.map((call) => call[2]?.offset)).toEqual([0, 50, 50]);
});

it("keeps a selected execution that is still on the reloaded page", async () => {
  const row = execution({
    seq: 9,
    node_id: "write",
    preview_only: true,
    output_preview: { inserted: 1 },
  });
  const refreshed = execution({
    seq: 9,
    node_id: "write",
    status: "running",
    preview_only: true,
    output_preview: { inserted: 2 },
  });
  vi.mocked(listExecutions)
    .mockResolvedValueOnce({ items: [row], total: 1, limit: 50, offset: 0 })
    .mockResolvedValueOnce({ items: [refreshed], total: 1, limit: 50, offset: 0 });
  const view = render(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 0,
      }),
    ),
  );

  fireEvent.click(await screen.findByRole("button", { name: "Write" }));
  expect(await screen.findByText("This execution stored a preview.")).toBeTruthy();
  view.rerender(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 1,
      }),
    ),
  );
  expect(await screen.findByText("channels.editor.status.running")).toBeTruthy();
  expect(screen.getByText("This execution stored a preview.")).toBeTruthy();
});

it("keeps a selected execution when the reader leaves its page and comes back", async () => {
  const first = execution({
    seq: 9,
    node_id: "write",
    preview_only: true,
    output_preview: { inserted: 1 },
  });
  const later = execution({ seq: 60, node_id: "write" });
  vi.mocked(listExecutions).mockImplementation(async (_channelId, _jobId, params) => {
    if (params?.offset === 50) {
      return { items: [later], total: 51, limit: 50, offset: 50 };
    }
    return { items: [first], total: 51, limit: 50, offset: 0 };
  });
  render(
    shell(createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph })),
  );

  fireEvent.click(await screen.findByRole("button", { name: "Write" }));
  expect(await screen.findByText("This execution stored a preview.")).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "2" })[0]);
  expect(await screen.findByText("51-51 of 51")).toBeTruthy();
  expect(screen.queryByText("This execution stored a preview.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "1" }));
  expect(await screen.findByText("1-50 of 51")).toBeTruthy();
  expect(screen.getByText("This execution stored a preview.")).toBeTruthy();
});

it("clears a selected execution that is absent after the reload", async () => {
  const selectedRow = execution({
    seq: 9,
    node_id: "write",
    preview_only: true,
    output_preview: { inserted: 1 },
  });
  const other = execution({ seq: 10, node_id: "write", status: "running" });
  const returned = execution({
    seq: 9,
    node_id: "write",
    status: "succeeded",
    preview_only: true,
    output_preview: { inserted: 1 },
  });
  vi.mocked(listExecutions)
    .mockResolvedValueOnce({ items: [selectedRow], total: 1, limit: 50, offset: 0 })
    .mockResolvedValueOnce({ items: [other], total: 1, limit: 50, offset: 0 })
    .mockResolvedValueOnce({ items: [returned], total: 1, limit: 50, offset: 0 });
  const view = render(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 0,
      }),
    ),
  );

  fireEvent.click(await screen.findByRole("button", { name: "Write" }));
  expect(await screen.findByText("This execution stored a preview.")).toBeTruthy();
  view.rerender(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 1,
      }),
    ),
  );
  expect(await screen.findByText("channels.editor.status.running")).toBeTruthy();
  expect(screen.queryByText("This execution stored a preview.")).toBeNull();

  view.rerender(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 2,
      }),
    ),
  );
  expect(await screen.findByText("channels.editor.status.succeeded")).toBeTruthy();
  expect(screen.queryByText("This execution stored a preview.")).toBeNull();
});

it("keeps the rows, the selection, and sends one notification when a parent reload fails", async () => {
  const child = execution({
    seq: 9,
    node_id: "write",
    preview_only: true,
    output_preview: { inserted: 1 },
  });
  vi.mocked(listExecutions)
    .mockResolvedValueOnce({ items: [child], total: 1, limit: 50, offset: 0 })
    .mockRejectedValueOnce(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-reload"));
  const view = render(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 0,
      }),
    ),
  );

  fireEvent.click(await screen.findByRole("button", { name: "Write" }));
  expect(await screen.findByText("This execution stored a preview.")).toBeTruthy();
  view.rerender(
    shell(
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
        reloadToken: 1,
      }),
    ),
  );

  expect(await screen.findAllByRole("alert")).toHaveLength(1);
  expect(screen.getByText("problems.unknown")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Write" })).toBeTruthy();
  expect(screen.getByText("This execution stored a preview.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
  expect(screen.queryByText("channels.run.outputFailed")).toBeNull();
});

it("does not load executions on its own timer", async () => {
  vi.mocked(listExecutions).mockResolvedValue({
    items: [execution({ seq: 1, node_id: "write" })],
    total: 1,
    limit: 50,
    offset: 0,
  });
  render(
    shell(createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph })),
  );
  expect(await screen.findByRole("button", { name: "Write" })).toBeTruthy();
  expect(listExecutions).toHaveBeenCalledTimes(1);

  vi.useFakeTimers();
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(listExecutions).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

it("keeps execution rows and sends one notification when a later refresh fails", async () => {
  const child = execution({ seq: 9, node_id: "write" });
  let rejectPage: (error: unknown) => void = () => {};
  vi.mocked(listExecutions)
    .mockResolvedValueOnce({ items: [child], total: 51, limit: 50, offset: 0 })
    .mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectPage = reject;
        }),
    );
  render(shell(createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph })));

  expect(await screen.findByRole("button", { name: "Write" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  await waitFor(() => expect(listExecutions).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("button", { name: "Write" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
  expect(screen.queryAllByRole("alert")).toHaveLength(0);

  rejectPage(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-later"));
  expect(await screen.findAllByRole("alert")).toHaveLength(1);
  expect(screen.getByText("problems.unknown")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Write" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
  expect(screen.queryByText("channels.run.outputFailed")).toBeNull();
});

it("shows the stored round plus one as text in the ledger column order", async () => {
  vi.mocked(listExecutions).mockResolvedValue({
    items: [
      execution({ seq: 1, node_id: "write", round: 0 }),
      execution({ seq: 2, node_id: "write", round: null }),
    ],
    total: 2,
    limit: 50,
    offset: 0,
  });
  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph }),
    ),
  );

  expect(await screen.findAllByRole("button", { name: "Write" })).toHaveLength(2);
  expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
    "channels.run.column.node",
    "channels.run.column.status",
    "channels.runs.started",
    "channels.run.column.executionRound",
    "channels.run.column.duration",
    "channels.run.column.outputBytes",
    "channels.run.column.error",
  ]);
  const rows = screen.getAllByRole("button", { name: "Write" }).map((button) => button.closest("tr"));
  const cells = (row: HTMLElement | null) => within(row as HTMLElement).getAllByRole("cell");
  expect(cells(rows[0])).toHaveLength(7);
  expect(cells(rows[0])[3].textContent).toBe("1");
  expect(within(rows[0] as HTMLElement).queryByRole("button", { name: "1" })).toBeNull();
  expect(cells(rows[1])[3].textContent).toBe("");
});

it("derives duration on render and moves a running row only when the table renders again", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-08-11T10:02:00.000Z"));
  const started = "2026-08-11T10:00:00.000Z";
  try {
    vi.mocked(listExecutions).mockResolvedValue({
      items: [
        execution({
          seq: 1,
          status: "succeeded",
          started_at: started,
          finished_at: "2026-08-11T10:00:45.000Z",
        }),
        execution({
          seq: 2,
          status: "running",
          started_at: started,
          finished_at: "2026-08-11T10:00:10.000Z",
        }),
        execution({
          seq: 3,
          status: "running",
          started_at: started,
          finished_at: null,
        }),
        execution({
          seq: 4,
          status: "failed",
          started_at: started,
          finished_at: null,
        }),
        execution({
          seq: 5,
          status: "succeeded",
          started_at: null,
          finished_at: "2026-08-11T10:00:45.000Z",
        }),
        execution({
          seq: 6,
          status: "failed",
          started_at: "2026-08-11T10:00:45.000Z",
          finished_at: started,
        }),
      ],
      total: 6,
      limit: 50,
      offset: 0,
    });
    const view = render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph }),
      ),
    );

    expect(await screen.findAllByRole("button", { name: "Write" })).toHaveLength(6);
    const duration = (index: number) => {
      const row = screen.getAllByRole("button", { name: "Write" })[index]?.closest("tr");
      return within(row as HTMLElement).getAllByRole("cell")[4].textContent;
    };
    expect(duration(0)).toBe("45s");
    expect(duration(1)).toBe("10s");
    expect(duration(2)).toBe("2m");
    expect(duration(3)).toBe("—");
    expect(duration(4)).toBe("—");
    expect(duration(5)).toBe("—");

    vi.setSystemTime(new Date("2026-08-11T10:03:00.000Z"));
    expect(duration(2)).toBe("2m");
    view.rerender(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph }),
      ),
    );
    expect(duration(2)).toBe("3m");
  } finally {
    vi.useRealTimers();
  }
});

it("shows the stored output byte count with no unit", async () => {
  vi.mocked(listExecutions).mockResolvedValue({
    items: [
      execution({ seq: 1, output_bytes: 4096 }),
      execution({ seq: 2, output_bytes: 0 }),
    ],
    total: 2,
    limit: 50,
    offset: 0,
  });
  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph }),
    ),
  );

  expect(await screen.findAllByRole("button", { name: "Write" })).toHaveLength(2);
  const bytes = (index: number) => {
    const row = screen.getAllByRole("button", { name: "Write" })[index]?.closest("tr");
    return within(row as HTMLElement).getAllByRole("cell")[5].textContent;
  };
  expect(bytes(0)).toBe("4096");
  expect(bytes(1)).toBe("0");
});

it("keeps seven columns on the loading ledger and widens the table floor", () => {
  vi.mocked(listExecutions).mockReturnValue(new Promise(() => {}));
  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionBrowser, { channelId: "chn_1", jobId: "job_1", graph }),
    ),
  );

  const bodyRow = screen.getAllByRole("row")[1];
  expect(within(bodyRow).getAllByRole("cell")).toHaveLength(7);
  const scroller = screen.getByRole("table").parentElement?.parentElement;
  expect(scroller?.getAttribute("style") ?? "").toContain(
    "--table-min-width: calc(52.5rem * var(--mantine-scale))",
  );
});

it("names the new ledger columns without reusing the container round mark", () => {
  const english = en as Record<string, string>;
  const chinese = zh as Record<string, string>;
  expect(english["channels.run.column.executionRound"]).toBe("Round");
  expect(english["channels.run.column.duration"]).toBe("Duration");
  expect(english["channels.run.column.outputBytes"]).toBe("Output bytes");
  expect(chinese["channels.run.column.executionRound"]).toBe("\u8f6e");
  expect(chinese["channels.run.column.duration"]).toBe("\u8017\u65f6");
  expect(chinese["channels.run.column.outputBytes"]).toBe("\u8f93\u51fa\u5b57\u8282");
  expect(english["channels.run.column.round"]).toBe("#");
  expect(chinese["channels.run.column.round"]).toBe("#");
});

it("tells execution clients to derive duration and leaves duration off the example", () => {
  const doc = readFileSync(resolve(process.cwd(), "../docs/api-contracts-data-channel.md"), "utf8");
  const section = doc.split("### 5.17 ")[1]?.split("### 5.18 ")[0] ?? "";
  const example = section.match(/```json([\s\S]*?)```/)?.[1] ?? "";
  expect(example).not.toContain('"duration"');
  const roundBullet = section.indexOf("`round` is the zero-based round index.");
  const durationBullet = section.indexOf(
    "Duration is derived by clients from `started_at` and `finished_at`.",
  );
  const previewBullet = section.indexOf("`output_preview` is the stored output");
  expect(roundBullet).toBeGreaterThan(-1);
  expect(durationBullet).toBeGreaterThan(roundBullet);
  expect(previewBullet).toBeGreaterThan(durationBullet);
});
