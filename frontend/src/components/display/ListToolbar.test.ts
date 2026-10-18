/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ListToolbar } from "@/components/display/ListToolbar";
import type { ListQuery } from "@/hooks/useListQuery";
import { SEARCH_DEBOUNCE_MS } from "@/hooks/useSearchDebounce";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
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

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

function queryOf(patch: Partial<ListQuery> = {}): ListQuery {
  return {
    searchEnabled: true,
    search: "",
    setSearch: vi.fn(),
    filters: [
      { key: "engine", type: "select", defaultValue: "" },
      { key: "status", type: "multi", defaultValue: ["open"] },
    ],
    select: () => "",
    multi: () => ["open"],
    setFilter: vi.fn(),
    page: 1,
    setPage: vi.fn(),
    clear: vi.fn(),
    isFiltered: false,
    ...patch,
  };
}

const fields = [
  {
    key: "engine",
    label: "Engine",
    options: [{ value: "pg", label: "PostgreSQL" }],
  },
];

describe("ListToolbar", () => {
  beforeEach(() => {
    stubDomApis();
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  function searchBox() {
    return screen.getByRole("textbox", { name: "common.list.search" });
  }

  it("debounces search, applies Enter immediately, and clears on Escape", () => {
    const query = queryOf();
    render(shell(createElement(ListToolbar, { query })));
    fireEvent.change(searchBox(), { target: { value: "alpha" } });
    expect(query.setSearch).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1);
    });
    expect(query.setSearch).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(query.setSearch).toHaveBeenCalledWith("alpha");

    fireEvent.change(searchBox(), { target: { value: "beta" } });
    fireEvent.keyDown(searchBox(), { key: "Enter" });
    expect(query.setSearch).toHaveBeenCalledWith("beta");
    act(() => {
      vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
    });
    expect(query.setSearch).toHaveBeenCalledTimes(2);

    fireEvent.change(searchBox(), { target: { value: "gone" } });
    fireEvent.keyDown(searchBox(), { key: "Escape" });
    expect(query.setSearch).toHaveBeenCalledWith("");
    act(() => {
      vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
    });
    expect(query.setSearch).not.toHaveBeenCalledWith("gone");
  });

  it("shows clear only when a filter is off default and focuses search on slash", () => {
    const idle = queryOf();
    const { rerender } = render(shell(createElement(ListToolbar, { query: idle })));
    expect(screen.queryByRole("button", { name: "common.filters.clear" })).toBeNull();

    const active = queryOf({ isFiltered: true, clear: vi.fn() });
    rerender(shell(createElement(ListToolbar, { query: active, filters: fields })));
    fireEvent.click(screen.getByRole("button", { name: "common.filters.clear" }));
    expect(active.clear).toHaveBeenCalledTimes(1);

    const other = document.createElement("input");
    document.body.append(other);
    other.focus();
    fireEvent.keyDown(other, { key: "/" });
    expect(document.activeElement).not.toBe(searchBox());

    const canvas = document.createElement("div");
    canvas.className = "react-flow";
    const node = document.createElement("button");
    node.type = "button";
    canvas.append(node);
    document.body.append(canvas);
    node.focus();
    fireEvent.keyDown(node, { key: "/" });
    expect(document.activeElement).not.toBe(searchBox());
    node.blur();

    fireEvent.keyDown(document.body, { key: "/" });
    expect(document.activeElement).toBe(searchBox());
  });

  it("shows the translated option label", () => {
    const query = queryOf();
    render(shell(createElement(ListToolbar, { query, filters: fields })));
    fireEvent.click(screen.getByRole("combobox", { name: "Engine" }));
    expect(screen.getByRole("option", { name: "PostgreSQL" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "pg" })).toBeNull();
  });
});
