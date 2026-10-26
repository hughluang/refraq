/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listDatasetRows } from "@/features/channels/api";
import { DatasetRowTable } from "@/features/channels/DatasetRows";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

vi.mock("@/features/channels/api", () => ({
  listDatasetRows: vi.fn(),
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
}

describe("DatasetRowTable", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows a dynamic time cell as the response string", async () => {
    const seenAt = "2024-01-02T01:02:03.123456+08:00";
    vi.mocked(listDatasetRows).mockResolvedValue({
      items: [{ _ord: 1, seen_at: seenAt }],
      limit: 1,
      next_after_ord: null,
    });
    render(
      createElement(
        MantineProvider,
        null,
        createElement(DatasetRowTable, {
          channelId: "chn_1",
          jobId: "job_1",
          datasetId: "dst_1",
          afterOrd: 0,
          endOrd: 1,
          columns: [{ name: "seen_at", type: "timestamp" }],
        }),
      ) as ReactNode,
    );

    expect(await screen.findByText(seenAt)).toBeTruthy();
    expect(listDatasetRows).toHaveBeenCalledWith("chn_1", "job_1", "dst_1", {
      after_ord: 0,
      limit: 1,
    });
  });
});
