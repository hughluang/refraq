/** @vitest-environment jsdom */

import { MantineProvider, Table } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ListTable, listTableMinWidth, type ListTableList } from "@/components/display/ListTable";
import type { ListPresentation } from "@/lib/list-state";
import { FEEDBACK_DELAY_MS } from "@/theme";

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

function list(presentation: ListPresentation, total = 0): ListTableList {
  return {
    presentation,
    error: null,
    errorRequestId: null,
    reload: () => {},
    page: 1,
    setPage: () => {},
    pageSize: 50,
    total,
  };
}

function table(
  presentation: ListPresentation,
  extra: {
    total?: number;
    emptyAction?: ReactNode;
    onClearFilters?: () => void;
    children?: ReactNode;
  } = {},
) {
  return createElement(ListTable, {
    list: list(presentation, extra.total),
    columnCount: 1,
    emptyAction: extra.emptyAction,
    onClearFilters: extra.onClearFilters,
    head: createElement(Table.Tr, null, createElement(Table.Th, null, "Name")),
    children: extra.children,
  });
}

describe("listTableMinWidth", () => {
  it("scales a short catalog and keeps an explicit floor", () => {
    expect(listTableMinWidth(2)).toBe(480);
    expect(listTableMinWidth(3)).toBe(720);
    expect(listTableMinWidth(4)).toBe(960);
    expect(listTableMinWidth(5)).toBe(1080);
    expect(listTableMinWidth(8)).toBe(1080);
    expect(listTableMinWidth(3, 640)).toBe(640);
  });
});

describe("ListTable status rows", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows unloaded instead of an empty list and retries from the status", () => {
    const reload = vi.fn();
    render(
      shell(
        createElement(ListTable, {
          list: {
            ...list({ state: "unloaded", refreshing: false }),
            error: "Load failed",
            errorRequestId: "req-1",
            reload,
          },
          columnCount: 2,
          emptyMessage: "Nothing here",
          emptyAction: createElement("button", { type: "button" }, "Create"),
          head: createElement(Table.Tr, null, createElement(Table.Th, null, "Name")),
          children: createElement(Table.Tr, null, createElement(Table.Td, null, "Secret row")),
        }),
      ),
    );

    const status = screen.getByRole("button", { name: "status.unloaded" });
    const badge = status.querySelector(".mantine-Badge-root");
    expect(badge?.getAttribute("style") ?? "").toContain("red");
    expect(status.closest("td")?.getAttribute("colspan")).toBe("2");
    expect(screen.queryByText("Secret row")).toBeNull();
    expect(screen.queryByText("Nothing here")).toBeNull();
    expect(screen.queryByText("common.empty")).toBeNull();
    expect(screen.queryByRole("button", { name: "Create" })).toBeNull();
    expect(screen.queryByText("Load failed")).toBeNull();
    expect(screen.queryByText("req-1")).toBeNull();
    expect(screen.queryByText("common.error")).toBeNull();
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
    fireEvent.click(status);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("keeps the problem alert when the list state is error", () => {
    const reload = vi.fn();
    render(
      shell(
        createElement(ListTable, {
          list: {
            ...list({ state: "error", refreshing: false }),
            error: "Load failed",
            errorRequestId: "req-1",
            reload,
          },
          columnCount: 2,
          emptyMessage: "Nothing here",
          emptyAction: createElement("button", { type: "button" }, "Create"),
          head: createElement(Table.Tr, null, createElement(Table.Th, null, "Name")),
          children: createElement(Table.Tr, null, createElement(Table.Td, null, "Secret row")),
        }),
      ),
    );

    expect(screen.getByText("common.error")).toBeTruthy();
    expect(screen.getByText("Load failed")).toBeTruthy();
    expect(screen.getByText(/req-1/)).toBeTruthy();
    expect(screen.queryByText("Secret row")).toBeNull();
    expect(screen.queryByText("status.unloaded")).toBeNull();
    expect(screen.queryByText("Nothing here")).toBeNull();
    expect(screen.queryByRole("button", { name: "Create" })).toBeNull();
    const retry = screen.getByRole("button", { name: "common.retry" });
    expect(retry.closest("td")?.getAttribute("colspan")).toBe("2");
    fireEvent.click(retry);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("keeps ready rows when a later failure still has them", () => {
    const row = createElement(Table.Tr, null, createElement(Table.Td, null, "Kept row"));
    render(
      shell(
        createElement(ListTable, {
          list: {
            ...list({ state: "ready", refreshing: false }, 1),
            error: "failed to load",
            errorRequestId: "req-2",
          },
          columnCount: 1,
          emptyAction: createElement("button", { type: "button" }, "Create"),
          head: createElement(Table.Tr, null, createElement(Table.Th, null, "Name")),
          children: row,
        }),
      ),
    );

    expect(screen.getByText("Kept row")).toBeTruthy();
    expect(screen.queryByText("status.unloaded")).toBeNull();
    expect(screen.queryByText("common.empty")).toBeNull();
    expect(screen.queryByRole("button", { name: "Create" })).toBeNull();
    expect(screen.queryByText("failed to load")).toBeNull();
    expect(screen.queryByText("req-2")).toBeNull();
  });

  it("offers the empty action and clear filters on no match", () => {
    const { rerender } = render(
      shell(
        table(
          { state: "empty", refreshing: false },
          { emptyAction: createElement("button", { type: "button" }, "Create") },
        ),
      ),
    );
    expect(screen.getByRole("button", { name: "Create" })).toBeTruthy();

    const onClear = vi.fn();
    rerender(
      shell(
        table({ state: "no-match", refreshing: false }, { onClearFilters: onClear }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.filters.clear" }));
    expect(onClear).toHaveBeenCalledTimes(1);

    rerender(shell(table({ state: "no-match", refreshing: false })));
    expect(screen.queryByRole("button", { name: "common.filters.clear" })).toBeNull();
  });

  it("dims existing rows only after the feedback delay", () => {
    vi.useFakeTimers();
    const row = createElement(Table.Tr, null, createElement(Table.Td, null, "Row"));
    const { rerender } = render(
      shell(
        table(
          { state: "ready", refreshing: true },
          { total: 1, children: row },
        ),
      ),
    );
    const body = document.querySelector("tbody");
    expect(body?.getAttribute("aria-busy")).toBe("true");
    expect(body?.style.opacity).toBe("");
    act(() => {
      vi.advanceTimersByTime(FEEDBACK_DELAY_MS - 1);
    });
    expect(body?.style.opacity).toBe("");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(body?.style.opacity).toBe("0.6");

    rerender(
      shell(
        table(
          { state: "ready", refreshing: false },
          { total: 1, children: row },
        ),
      ),
    );
    expect(body?.style.opacity).toBe("");

    rerender(
      shell(
        table(
          { state: "ready", refreshing: true },
          { total: 1, children: row },
        ),
      ),
    );
    act(() => {
      vi.advanceTimersByTime(FEEDBACK_DELAY_MS - 1);
    });
    rerender(
      shell(
        table(
          { state: "ready", refreshing: false },
          { total: 1, children: row },
        ),
      ),
    );
    act(() => {
      vi.advanceTimersByTime(FEEDBACK_DELAY_MS);
    });
    expect(document.querySelector("tbody")?.style.opacity).toBe("");
  });
});
