/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { listDatasetRows, listExecutions, previewTemplate } from "@/features/channels/api";
import { RunExecutionBrowser } from "@/features/channels/RunExecutionBrowser";
import { EMPTY_GRAPH, type Graph, type NodeExecution } from "@/features/channels/types";
import { ApiError } from "@/lib/api";
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
