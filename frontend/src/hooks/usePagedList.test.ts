/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { usePagedList } from "@/hooks/usePagedList";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

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
});
