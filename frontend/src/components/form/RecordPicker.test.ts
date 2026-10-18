/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  RecordMultiPicker,
  RecordPicker,
  RECORD_PICKER_DEBOUNCE_MS,
} from "@/components/form/RecordPicker";
import type { RecordOption, RecordPickerAdapter } from "@/components/form/recordPickerAdapters";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useNotification: () => ({ open: vi.fn() }),
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
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
}

function mount(node: ReturnType<typeof createElement>) {
  return render(createElement(MantineProvider, { env: "test" }, node));
}

function adapter(search: RecordPickerAdapter["search"], resolve: RecordPickerAdapter["resolve"]): RecordPickerAdapter {
  return { search, resolve };
}

const ada: RecordOption = { id: "user_1", name: "Ada Lovelace", key: "ada" };

describe("RecordPicker", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("debounces server search", async () => {
    vi.useFakeTimers();
    const search = vi.fn(async () => [ada]);
    mount(
      createElement(RecordPicker, {
        editable: true,
        label: "Owner",
        adapter: adapter(search, async () => []),
        value: null,
        onChange: () => {},
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Owner" }));
    const box = screen.getByRole("textbox", { name: "recordPicker.placeholder" });
    fireEvent.change(box, { target: { value: "ada" } });
    expect(search).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECORD_PICKER_DEBOUNCE_MS - 1);
    });
    expect(search).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(search).toHaveBeenCalledWith("ada", expect.any(AbortSignal));
  });

  it("resolves a preselected id to its name and key", async () => {
    const resolve = vi.fn(async () => [ada]);
    mount(
      createElement(RecordPicker, {
        editable: true,
        label: "Owner",
        adapter: adapter(async () => [], resolve),
        value: "user_1",
        onChange: () => {},
      }),
    );
    expect(await screen.findByText("Ada Lovelace")).toBeTruthy();
    expect(screen.getByText("ada")).toBeTruthy();
    expect(resolve).toHaveBeenCalledWith(["user_1"], expect.any(AbortSignal));
  });

  it("shows searching, then no result", async () => {
    let finish: (options: RecordOption[]) => void = () => {};
    const search = vi.fn(
      () =>
        new Promise<RecordOption[]>((resolve) => {
          finish = resolve;
        }),
    );
    mount(
      createElement(RecordPicker, {
        editable: true,
        label: "Owner",
        adapter: adapter(search, async () => []),
        value: null,
        onChange: () => {},
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Owner" }));
    expect(await screen.findByText("recordPicker.searching")).toBeTruthy();
    finish([]);
    expect(await screen.findByText("recordPicker.empty")).toBeTruthy();
  });

  it("shows an error and retries", async () => {
    const search = vi
      .fn<RecordPickerAdapter["search"]>()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce([ada]);
    mount(
      createElement(RecordPicker, {
        editable: true,
        label: "Owner",
        adapter: adapter(search, async () => []),
        value: null,
        onChange: () => {},
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Owner" }));
    expect(await screen.findByText("common.error.loadFailed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByText("Ada Lovelace")).toBeTruthy();
    expect(search).toHaveBeenCalledTimes(2);
  });

  it("ignores a stale response", async () => {
    vi.useFakeTimers();
    let resolveFirst: (options: RecordOption[]) => void = () => {};
    const search = vi.fn((q: string) => {
      if (q === "a") {
        return new Promise<RecordOption[]>((resolve) => {
          resolveFirst = resolve;
        });
      }
      return Promise.resolve([{ id: "user_2", name: "Able", key: "able" }]);
    });
    mount(
      createElement(RecordPicker, {
        editable: true,
        label: "Owner",
        adapter: adapter(search, async () => []),
        value: null,
        onChange: () => {},
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Owner" }));
    const box = screen.getByRole("textbox", { name: "recordPicker.placeholder" });
    fireEvent.change(box, { target: { value: "a" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECORD_PICKER_DEBOUNCE_MS);
    });
    fireEvent.change(box, { target: { value: "ab" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECORD_PICKER_DEBOUNCE_MS);
    });
    expect(screen.getByText("Able")).toBeTruthy();
    await act(async () => {
      resolveFirst([{ id: "user_1", name: "Stale", key: "stale" }]);
      await Promise.resolve();
    });
    expect(screen.queryByText("Stale")).toBeNull();
    expect(screen.getByText("Able")).toBeTruthy();
  });

  it("adds and removes records", async () => {
    const onChange = vi.fn();
    mount(
      createElement(RecordMultiPicker, {
        editable: true,
        label: "Members",
        adapter: adapter(async () => [ada], async () => []),
        value: [],
        onChange,
      }),
    );
    fireEvent.focus(screen.getByRole("textbox", { name: "Members" }));
    fireEvent.click(await screen.findByRole("option", { name: /Ada Lovelace/ }));
    expect(onChange).toHaveBeenCalledWith(["user_1"]);
    cleanup();
    mount(
      createElement(RecordMultiPicker, {
        editable: true,
        label: "Members",
        adapter: adapter(async () => [ada], async () => [ada]),
        value: ["user_1"],
        onChange,
      }),
    );
    expect(await screen.findByText("Ada Lovelace")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "recordPicker.remove Ada Lovelace" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("renders the resolved record in display mode", async () => {
    mount(
      createElement(RecordPicker, {
        editable: false,
        label: "Owner",
        adapter: adapter(async () => [], async () => [ada]),
        value: "user_1",
      }),
    );
    expect(await screen.findByText("Ada Lovelace")).toBeTruthy();
    expect(screen.getByText("ada")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Owner" })).toBeNull();
  });
});
