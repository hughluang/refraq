/** @vitest-environment jsdom */
import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";
import { ConsoleNotifications } from "@/providers/notification-provider";

const harness = vi.hoisted(() => ({
  open: vi.fn(),
  dictionary: {
    "problems.REQUEST_INVALID": "The request is not valid. Check the fields and try again.",
    "problems.unknown": "Something went wrong. Try again.",
    "form.error.details": "Details",
    "form.error.copy": "Copy details",
    "common.requestId": "Request ID",
    "common.copy.success": "Copied",
    "common.copy.failed": "Copy failed",
    "common.retry": "Retry",
  } as Record<string, string>,
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => harness.dictionary[key] ?? key,
  useNotification: () => ({ open: harness.open }),
}));

function pageOf<T>(items: T[], query: PageQuery): OffsetPage<T> {
  return {
    items: items.slice(query.offset, query.offset + query.limit),
    total: items.length,
    limit: query.limit,
    offset: query.offset,
  };
}

describe("usePagedList resetDeps reload", () => {
  it("reloads on page 1 when only resetDeps change (stable fetch)", async () => {
    const fetch = vi.fn((query: PageQuery) => pageOf(["a", "b", "c"], query));
    const { result, rerender } = renderHook(
      ({ resetDeps }) =>
        usePagedList({
          pageSize: 50,
          fetch,
          resetDeps,
          initialLoading: false,
        }),
      { initialProps: { resetDeps: ["q1"] as readonly unknown[] } },
    );

    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]![0]).toEqual({ limit: 50, offset: 0 });
    expect(result.current.page).toBe(1);
    expect(result.current.items).toEqual(["a", "b", "c"]);

    rerender({ resetDeps: ["q2"] });
    await act(async () => {});

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1]![0]).toEqual({ limit: 50, offset: 0 });
  });

  it("does not reload when resetDeps and fetch are unchanged", async () => {
    const fetch = vi.fn((query: PageQuery) => pageOf(["x"], query));
    const { rerender } = renderHook(
      ({ resetDeps }) =>
        usePagedList({
          pageSize: 50,
          fetch,
          resetDeps,
          initialLoading: false,
        }),
      { initialProps: { resetDeps: ["same"] as readonly unknown[] } },
    );

    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(1);

    rerender({ resetDeps: ["same"] });
    await act(async () => {});

    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("resets from page 2 with a single fetch at offset 0", async () => {
    const fetch = vi.fn((query: PageQuery) =>
      pageOf(Array.from({ length: 120 }, (_, i) => `row-${i}`), query),
    );
    const { result, rerender } = renderHook(
      ({ resetDeps }) =>
        usePagedList({
          pageSize: 50,
          fetch,
          resetDeps,
          initialLoading: false,
        }),
      { initialProps: { resetDeps: [""] as readonly unknown[] } },
    );

    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.setPage(2);
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1]![0]).toEqual({ limit: 50, offset: 50 });
    expect(result.current.page).toBe(2);

    rerender({ resetDeps: ["filter"] });
    await act(async () => {});

    expect(result.current.page).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[2]![0]).toEqual({ limit: 50, offset: 0 });
  });

  it("skips fetch when enabled is false and clears total", async () => {
    const fetch = vi.fn((query: PageQuery) => pageOf(["hidden"], query));
    const { result } = renderHook(() =>
      usePagedList({
        pageSize: 50,
        fetch,
        enabled: false,
        initialLoading: false,
      }),
    );

    await act(async () => {});

    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.total).toBe(0);
    expect(result.current.items).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("uses a controlled page and asks the owner to reset it", async () => {
    const fetch = vi.fn((query: PageQuery) =>
      pageOf(Array.from({ length: 120 }, (_, index) => `row-${index}`), query),
    );
    const onPageChange = vi.fn();
    const { result, rerender } = renderHook(
      ({ resetDeps, page }) =>
        usePagedList({
          pageSize: 50,
          fetch,
          resetDeps,
          page,
          onPageChange,
          initialLoading: false,
        }),
      { initialProps: { resetDeps: ["a"] as readonly unknown[], page: 2 } },
    );

    await act(async () => {});
    expect(fetch.mock.calls[0]?.[0]).toEqual({ limit: 50, offset: 50 });
    expect(onPageChange).not.toHaveBeenCalled();

    rerender({ resetDeps: ["b"], page: 2 });
    await act(async () => {});
    expect(result.current.page).toBe(1);
    expect(onPageChange).toHaveBeenCalledWith(1);
    expect(fetch.mock.calls.at(-1)?.[0]).toEqual({ limit: 50, offset: 0 });
  });
});

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

describe("useConsolePagedList", () => {
  beforeEach(() => {
    stubDomApis();
    harness.open.mockClear();
    resetNotifications();
    render(createElement(MantineProvider, { env: "test" }, createElement(ConsoleNotifications)));
  });

  afterEach(() => {
    resetNotifications();
    cleanup();
  });

  it("notifies once with server detail, request id, and retry when the first load fails", async () => {
    const fetch = vi.fn((_query: PageQuery) =>
      Promise.reject(new ApiError(422, "REQUEST_INVALID", "bad offset", "req-9")),
    );
    const { result } = renderHook(() =>
      useConsolePagedList({
        pageSize: 50,
        fetch,
        initialLoading: false,
      }),
    );

    await act(async () => {});

    expect(harness.open).not.toHaveBeenCalled();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("The request is not valid. Check the fields and try again.")).toBeTruthy();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("bad offset").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-9").closest("details")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(result.current.items).toEqual([]);
    expect(result.current.presentation.state).toBe("unloaded");
  });

  it("clears the unloaded status after a successful retry", async () => {
    const fetch = vi.fn((query: PageQuery) => {
      if (fetch.mock.calls.length === 1) {
        return Promise.reject(new ApiError(422, "REQUEST_INVALID", "bad offset", "req-9"));
      }
      return Promise.resolve(pageOf(["row-a"], query));
    });
    const { result } = renderHook(() =>
      useConsolePagedList({
        pageSize: 50,
        fetch,
        initialLoading: false,
      }),
    );

    await act(async () => {});
    expect(result.current.presentation.state).toBe("unloaded");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    });

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.items).toEqual(["row-a"]);
    expect(result.current.error).toBeNull();
    expect(result.current.errorRequestId).toBeNull();
    expect(result.current.presentation.state).toBe("ready");
    expect(harness.open).not.toHaveBeenCalled();
  });

  it("keeps the rows and notifies once when a later refresh fails", async () => {
    const fetch = vi.fn((query: PageQuery) => {
      if (fetch.mock.calls.length === 1) return Promise.resolve(pageOf(["row-a", "row-b"], query));
      return Promise.reject(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-later"));
    });
    const { result } = renderHook(() =>
      useConsolePagedList({
        pageSize: 50,
        fetch,
        initialLoading: false,
      }),
    );

    await act(async () => {});
    expect(result.current.items).toEqual(["row-a", "row-b"]);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.items).toEqual(["row-a", "row-b"]);
    expect(result.current.presentation.state).toBe("ready");
    expect(harness.open).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("Something went wrong. Try again.")).toBeTruthy();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("upstream timed out").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-later").closest("details")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
