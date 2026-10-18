/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useListQuery, type ListFilterSpec } from "@/hooks/useListQuery";
import { usePagedList } from "@/hooks/usePagedList";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

const nav = vi.hoisted(() => ({
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
}));

const STATUS: readonly ListFilterSpec[] = [
  { key: "status", type: "multi", defaultValue: ["not_serving", "serving"] },
];

function pageOf<T>(items: T[], query: PageQuery): OffsetPage<T> {
  return {
    items: items.slice(query.offset, query.offset + query.limit),
    total: items.length,
    limit: query.limit,
    offset: query.offset,
  };
}

function setup(search: string) {
  const path = search ? `/console/entities?${search}` : "/console/entities";
  window.history.replaceState(null, "", path);
  nav.params = new URLSearchParams(search);
}

describe("useListQuery", () => {
  let replaceState: ReturnType<typeof vi.spyOn>;
  let pushState: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    setup("");
    replaceState = vi.spyOn(window.history, "replaceState");
    pushState = vi.spyOn(window.history, "pushState");
  });

  afterEach(() => {
    replaceState.mockRestore();
    pushState.mockRestore();
  });

  function open(search: string) {
    setup(search);
    replaceState.mockClear();
    pushState.mockClear();
    return renderHook(() => useListQuery({ filters: STATUS }));
  }

  function href(): string {
    return String(replaceState.mock.calls.at(-1)?.[2] ?? "");
  }

  it("restores search, filters, and page from the URL and omits defaults on write", () => {
    const { result } = open("q=alpha&status=deprecated&page=3&tab=overview");
    expect(result.current.search).toBe("alpha");
    expect(result.current.multi("status")).toEqual(["deprecated"]);
    expect(result.current.page).toBe(3);
    expect(result.current.isFiltered).toBe(true);
    expect(replaceState).not.toHaveBeenCalled();

    act(() => {
      result.current.setSearch("beta");
    });
    expect(pushState).not.toHaveBeenCalled();
    expect(replaceState).toHaveBeenCalled();
    expect(href()).toContain("q=beta");
    expect(href()).toContain("status=deprecated");
    expect(href()).toContain("tab=overview");
    expect(href()).not.toContain("page=");
    expect(result.current.page).toBe(1);

    act(() => {
      result.current.setFilter("status", ["serving", "not_serving"]);
    });
    expect(href()).toContain("q=beta");
    expect(href()).toContain("tab=overview");
    expect(href()).not.toContain("status=");
    expect(href()).not.toContain("page=");
    expect(result.current.isFiltered).toBe(true);

    act(() => {
      result.current.clear();
    });
    expect(href()).toBe("/console/entities?tab=overview");
    expect(result.current.search).toBe("");
    expect(result.current.page).toBe(1);
    expect(result.current.isFiltered).toBe(false);
    expect(pushState).not.toHaveBeenCalled();
  });

  it("omits a default page and writes a later page with replaceState", () => {
    const { result } = open("tab=overview");
    act(() => {
      result.current.setPage(1);
    });
    expect(replaceState).not.toHaveBeenCalled();

    act(() => {
      result.current.setPage(4);
    });
    expect(href()).toBe("/console/entities?tab=overview&page=4");
    expect(pushState).not.toHaveBeenCalled();

    act(() => {
      result.current.setFilter("status", ["deprecated"]);
    });
    expect(href()).toContain("status=deprecated");
    expect(href()).not.toContain("page=");
    expect(result.current.page).toBe(1);
  });

  it("restores a shared link when search params change", async () => {
    const { result, rerender } = open("");
    nav.params = new URLSearchParams("q=shared&page=2&status=deprecated");
    window.history.replaceState(
      null,
      "",
      "/console/entities?q=shared&page=2&status=deprecated",
    );
    rerender();
    await act(async () => {});
    expect(result.current.search).toBe("shared");
    expect(result.current.page).toBe(2);
    expect(result.current.multi("status")).toEqual(["deprecated"]);
  });

  it("drives usePagedList page and resets it when a filter changes", async () => {
    const rows = Array.from({ length: 80 }, (_, index) => `row-${index}`);
    const fetch = vi.fn((query: PageQuery) => pageOf(rows, query));
    setup("");
    replaceState.mockClear();
    const { result } = renderHook(() => {
      const query = useListQuery({ filters: STATUS });
      const list = usePagedList({
        pageSize: 50,
        fetch,
        resetDeps: [query.search, query.multi("status")],
        page: query.page,
        onPageChange: query.setPage,
        initialLoading: false,
      });
      return { query, list };
    });
    await act(async () => {});
    expect(fetch.mock.calls[0]?.[0]).toEqual({ limit: 50, offset: 0 });

    await act(async () => {
      result.current.list.setPage(2);
    });
    expect(result.current.query.page).toBe(2);
    expect(result.current.list.page).toBe(2);
    expect(fetch.mock.calls.at(-1)?.[0]).toEqual({ limit: 50, offset: 50 });
    expect(href()).toContain("page=2");
    expect(pushState).not.toHaveBeenCalled();

    await act(async () => {
      result.current.query.setSearch("alpha");
    });
    expect(result.current.query.page).toBe(1);
    expect(result.current.list.page).toBe(1);
    expect(fetch.mock.calls.at(-1)?.[0]).toEqual({ limit: 50, offset: 0 });
    expect(href()).toContain("q=alpha");
    expect(href()).not.toContain("page=");
  });
});
