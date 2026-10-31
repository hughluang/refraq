/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listDatasetRows } from "@/features/channels/api";
import { DatasetRowTable } from "@/features/channels/DatasetRows";
import { ApiError } from "@/lib/api";
import { bindClientI18n } from "@/providers/i18n-runtime";
import { ConsoleNotifications } from "@/providers/notification-provider";

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

describe("DatasetRowTable", () => {
  beforeEach(() => {
    stubDomApis();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    bindClientI18n({ t: (key: string) => key } as never);
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

  it("shows unloaded and one notification when the first row load fails", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    vi.mocked(listDatasetRows).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-rows"),
    );
    render(
      shell(
        createElement(DatasetRowTable, {
          channelId: "chn_1",
          jobId: "job_1",
          datasetId: "dst_1",
          afterOrd: 0,
          endOrd: 1,
          columns: [{ name: "code", type: "string" }],
        }),
      ),
    );

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("channels.run.rowsFailed")).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => expect(listDatasetRows).toHaveBeenCalledTimes(2));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown Repeated 2 times")).toBeTruthy();
  });

  it("keeps rows on screen through a failed refresh and notifies once", async () => {
    let rejectPage: (error: unknown) => void = () => {};
    vi.mocked(listDatasetRows)
      .mockResolvedValueOnce({
        items: [{ _ord: 1, code: "KEEP" }],
        limit: 200,
        next_after_ord: null,
      })
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectPage = reject;
          }),
      );
    render(
      shell(
        createElement(DatasetRowTable, {
          channelId: "chn_1",
          jobId: "job_1",
          datasetId: "dst_1",
          afterOrd: 0,
          endOrd: 400,
          columns: [{ name: "code", type: "string" }],
        }),
      ),
    );

    expect(await screen.findByText("KEEP")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    await waitFor(() => expect(listDatasetRows).toHaveBeenCalledTimes(2));
    expect(screen.getByText("KEEP")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    rejectPage(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-later"));
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.getByText("KEEP")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryByText("channels.run.rowsFailed")).toBeNull();
  });
});
