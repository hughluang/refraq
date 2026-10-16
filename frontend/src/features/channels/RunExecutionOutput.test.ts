/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { getExecutionOutput } from "@/features/channels/api";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import type { NodeExecution } from "@/features/channels/types";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) =>
    ({
      "channels.run.showFullOutput": "Show full output",
      "channels.run.outputFailed": "Output failed",
    })[key] ?? key,
}));

vi.mock("@/features/channels/api", () => ({
  getExecutionOutput: vi.fn(),
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
