/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { LIVE_STATUS_INTERVAL_MS, useLiveStatus } from "@/hooks/useLiveStatus";
import { ConsoleNotifications } from "@/providers/notification-provider";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

type Row = { status: string };

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

function Probe({
  load,
  isTerminal = () => false,
}: {
  load: (signal: AbortSignal) => Promise<Row>;
  isTerminal?: (row: Row) => boolean;
}) {
  const live = useLiveStatus({
    fetch: load,
    isTerminal,
  });
  const label = live.data?.status ?? "";
  return createElement(
    "div",
    null,
    createElement("div", { "data-testid": "value" }, label || "none"),
    createElement("div", { "data-testid": "updated" }, live.lastSuccessAt ?? ""),
    createElement("div", { "data-testid": "stale" }, live.stale ? "stale" : "fresh"),
    createElement(LiveStatusAnnouncer, { text: label }),
    createElement(
      "button",
      {
        type: "button",
        onClick: () => {
          void live.refresh();
        },
      },
      "Refresh",
    ),
  );
}

function renderProbe(
  load: (signal: AbortSignal) => Promise<Row>,
  isTerminal?: (row: Row) => boolean,
) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(Probe, { load, isTerminal }),
    ),
  );
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
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
  setHidden(false);
  vi.useRealTimers();
});

describe("useLiveStatus", () => {
  it("discovers terminal collections quietly and coalesces automatic requests", async () => {
    const result = vi.fn();
    const load = vi.fn().mockResolvedValueOnce({ status: "succeeded" })
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementation(() => new Promise<Row>(() => {}));
    function Collection() {
      const live = useLiveStatus({ fetch: load, isTerminal: () => true,
        terminalIntervalMs: 30000, onRefreshResult: result });
      return createElement("div", null, live.stale ? "stale collection" : "fresh collection");
    }
    render(createElement(Collection));
    await advance(0);
    await advance(30000);
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByText("stale collection")).toBeTruthy();
    expect(result).not.toHaveBeenCalled();
    await advance(30000);
    act(() => { setHidden(true); setHidden(false); });
    await advance(30000);
    expect(load).toHaveBeenCalledTimes(3);
  });
  it("aborts old collection requests when the query key changes", async () => {
    const signals: AbortSignal[] = [];
    const load = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      return new Promise<Row>(() => {});
    });
    function Collection({ query }: { query: string }) {
      useLiveStatus({ key: query, fetch: load, isTerminal: () => false });
      return null;
    }
    const view = render(createElement(Collection, { query: "all" }));
    await advance(0);
    view.rerender(createElement(Collection, { query: "failed" }));
    await advance(0);
    expect(signals).toHaveLength(2);
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
  });

  it("keeps polling after a manual refresh supersedes a hung automatic request", async () => {
    const signals: AbortSignal[] = [];
    const load = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      return signals.length === 1 ? new Promise<Row>(() => {}) : Promise.resolve({ status: "running" });
    });
    renderProbe(load);
    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await advance(0);
    expect(signals[0].aborted).toBe(true);
    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("polls on the interval while the status is non-terminal", async () => {
    const load = vi
      .fn<(signal: AbortSignal) => Promise<Row>>()
      .mockResolvedValueOnce({ status: "running" })
      .mockResolvedValue({ status: "succeeded" });
    renderProbe(load);

    await advance(0);
    expect(load).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("value").textContent).toBe("running");
    expect(screen.getByRole("status").textContent).toBe("");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("value").textContent).toBe("succeeded");
    expect(screen.getByRole("status").textContent).toBe("succeeded");
  });

  it("stops polling once the result is terminal", async () => {
    const load = vi
      .fn<(signal: AbortSignal) => Promise<Row>>()
      .mockResolvedValue({ status: "succeeded" });
    renderProbe(load, (row) => row.status === "succeeded");
    await advance(0);
    expect(load).toHaveBeenCalledTimes(1);

    await advance(LIVE_STATUS_INTERVAL_MS * 3);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("pauses while the document is hidden and refreshes when it is visible again", async () => {
    const load = vi.fn<(signal: AbortSignal) => Promise<Row>>().mockResolvedValue({
      status: "running",
    });
    renderProbe(load);
    await advance(0);
    expect(load).toHaveBeenCalledTimes(1);

    await act(async () => {
      setHidden(true);
    });
    await advance(LIVE_STATUS_INTERVAL_MS * 3);
    expect(load).toHaveBeenCalledTimes(1);

    await act(async () => {
      setHidden(false);
    });
    await advance(0);
    expect(load).toHaveBeenCalledTimes(2);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("keeps the last result and shows a stale retry after a failed refresh", async () => {
    const load = vi
      .fn<(signal: AbortSignal) => Promise<Row>>()
      .mockResolvedValueOnce({ status: "running" })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ status: "running" });
    renderProbe(load);
    await advance(0);
    expect(screen.getByTestId("value").textContent).toBe("running");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByTestId("value").textContent).toBe("running");
    expect(screen.getByTestId("stale").textContent).toBe("stale");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await advance(0);
    expect(load).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("stale").textContent).toBe("fresh");
  });

  it("ignores a response from an earlier request", async () => {
    let resolveFirst: (row: Row) => void = () => {};
    const load = vi.fn<(signal: AbortSignal) => Promise<Row>>((_signal) => {
      if (load.mock.calls.length === 1) {
        return new Promise<Row>((resolve) => {
          resolveFirst = resolve;
        });
      }
      return Promise.resolve({ status: "succeeded" });
    });
    renderProbe(load);
    await advance(0);
    expect(load).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("value").textContent).toBe("none");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await advance(0);
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("value").textContent).toBe("succeeded");

    await act(async () => {
      resolveFirst({ status: "running" });
    });
    expect(screen.getByTestId("value").textContent).toBe("succeeded");
  });

  it("keeps the last successful update and does not notify when a later poll fails", async () => {
    const state = notificationsStore.getState();
    for (const item of [...state.notifications, ...state.queue]) {
      notifications.hide(item.id);
    }
    notifications.clean();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    const load = vi
      .fn<(signal: AbortSignal) => Promise<Row>>()
      .mockResolvedValueOnce({ status: "running" })
      .mockRejectedValueOnce(new Error("offline"));
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ConsoleNotifications),
        createElement(Probe, { load }),
      ),
    );

    await advance(0);
    expect(screen.getByTestId("value").textContent).toBe("running");
    expect(screen.getByTestId("updated").textContent).toBe("2026-10-11T06:00:29.000Z");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("value").textContent).toBe("running");
    expect(screen.getByTestId("updated").textContent).toBe("2026-10-11T06:00:29.000Z");
    expect(screen.getByTestId("stale").textContent).toBe("stale");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("aborts the in-flight request when the watcher unmounts", async () => {
    let signal: AbortSignal | undefined;
    const load = vi.fn<(signal: AbortSignal) => Promise<Row>>((next) => {
      signal = next;
      return new Promise<Row>(() => {});
    });
    const view = renderProbe(load);
    await advance(0);
    expect(signal?.aborted).toBe(false);
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
