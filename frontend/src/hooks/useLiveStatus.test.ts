/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StaleNotice } from "@/components/display/StaleNotice";
import { LIVE_STATUS_INTERVAL_MS, useLiveStatus } from "@/hooks/useLiveStatus";

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
    createElement(LiveStatusAnnouncer, { text: label }),
    live.stale
      ? createElement(StaleNotice, {
          hasData: live.data != null,
          onRetry: () => {
            void live.refresh();
          },
        })
      : null,
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
    expect(screen.getByText("liveStatus.stale")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await advance(0);
    expect(load).toHaveBeenCalledTimes(3);
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
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

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("value").textContent).toBe("succeeded");

    await act(async () => {
      resolveFirst({ status: "running" });
    });
    expect(screen.getByTestId("value").textContent).toBe("succeeded");
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
