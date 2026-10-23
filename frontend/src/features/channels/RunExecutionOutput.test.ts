/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { getExecutionOutput, listDatasetRows } from "@/features/channels/api";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import type { NodeExecution } from "@/features/channels/types";
import { ApiError } from "@/lib/api";

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
        "common.showing": "{{from}}-{{to}} of {{total}}",
        "channels.run.dataset.reason.expired": "This dataset has expired",
        "channels.run.rowsFailed": "The rows could not be loaded",
      })[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
}));

vi.mock("@/features/channels/api", () => ({
  getExecutionOutput: vi.fn(),
  listDatasetRows: vi.fn(),
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

it("loads every page when a recorded output preview is truncated", async () => {
  vi.mocked(getExecutionOutput)
    .mockResolvedValueOnce({ items: [1, 2], total: 3, limit: 2, offset: 0 })
    .mockResolvedValueOnce({ items: [3], total: 3, limit: 2, offset: 2 });
  const item = {
    seq: 4,
    status: "succeeded",
    output_preview: [1],
    output_truncated: true,
  } as NodeExecution;

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionOutput, {
        channelId: "chn_1",
        jobId: "job_1",
        item,
      }),
    ),
  );

  fireEvent.click(screen.getByRole("button", { name: "Show full output" }));
  await waitFor(() => expect(screen.getByText(/1,\s+2,\s+3/)).toBeTruthy());
  expect(getExecutionOutput).toHaveBeenNthCalledWith(1, "chn_1", "job_1", 4, {
    limit: 200,
    offset: 0,
  });
  expect(getExecutionOutput).toHaveBeenNthCalledWith(2, "chn_1", "job_1", 4, {
    limit: 200,
    offset: 2,
  });
});

it("shows a dataset card and pages its rows instead of the output endpoint", async () => {
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
  const item = {
    seq: 2,
    status: "succeeded",
    output_preview: {
      dataset: {
        dataset_id: "dst_1",
        columns: [{ name: "code", type: "string" }],
        count: 250,
      },
      count: 250,
    },
    output_truncated: true,
    preview_only: false,
  } as NodeExecution;

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionOutput, { channelId: "chn_1", jobId: "job_1", item }),
    ),
  );

  expect(screen.getByText("Dataset reference")).toBeTruthy();
  expect(screen.getByText("dst_1")).toBeTruthy();
  expect(screen.getByText("code (string)")).toBeTruthy();
  expect(screen.getByText("250 rows")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Show full output" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Show rows" }));
  await waitFor(() => expect(screen.getByText("S-01")).toBeTruthy());
  expect(listDatasetRows).toHaveBeenCalledWith("chn_1", "job_1", "dst_1", {
    after_ord: 0,
    limit: 200,
  });
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  await waitFor(() => expect(screen.getByText("S-03")).toBeTruthy());
  expect(listDatasetRows).toHaveBeenLastCalledWith("chn_1", "job_1", "dst_1", {
    after_ord: 200,
    limit: 50,
  });
  expect(getExecutionOutput).not.toHaveBeenCalled();
});

it("shows why a dataset cannot be read and does not offer regeneration", async () => {
  vi.mocked(listDatasetRows).mockRejectedValue(
    new ApiError(404, "CHANNEL_DATASET_UNAVAILABLE", "Dataset is not available", null, {
      reason: "expired",
    }),
  );
  const item = {
    seq: 2,
    status: "succeeded",
    output_preview: {
      dataset_id: "dst_old",
      columns: [{ name: "code", type: "string" }],
      count: 4,
    },
    output_truncated: false,
    preview_only: false,
  } as NodeExecution;

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionOutput, { channelId: "chn_1", jobId: "job_1", item }),
    ),
  );

  fireEvent.click(screen.getByRole("button", { name: "Show rows" }));
  await waitFor(() => expect(screen.getByText("This dataset has expired")).toBeTruthy());
  expect(screen.queryByRole("button", { name: /regenerat/i })).toBeNull();
  expect(screen.queryByText(/regenerat/i)).toBeNull();
});

it("shows the stored preview total and does not page the output endpoint", () => {
  const item = {
    seq: 8,
    status: "succeeded",
    output_preview: { rows: [1] },
    output_truncated: true,
    preview_only: true,
    preview_totals: { rows: 1000000 },
  } as NodeExecution;

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionOutput, { channelId: "chn_1", jobId: "job_1", item }),
    ),
  );

  expect(screen.getByText("This execution stored a preview.")).toBeTruthy();
  expect(screen.getByText("rows total 1000000")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Show full output" })).toBeNull();
  expect(getExecutionOutput).not.toHaveBeenCalled();
  expect(listDatasetRows).not.toHaveBeenCalled();
});
