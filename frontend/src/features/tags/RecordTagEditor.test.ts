/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listTags } from "@/features/tags/api";

const LABELS: Record<string, string> = {
  "tags.editor.searching": "Looking up tags",
  "tags.editor.searchFailed":
    "Couldn't look up tags. You can still save the name you typed.",
  "tags.editor.limit": "A record can carry ten tags.",
  "tags.editor.new": "New",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name] ?? ""));
  },
}));

vi.mock("@/features/tags/api", () => ({
  listTags: vi.fn(async () => ({ items: [], total: 0, limit: 8, offset: 0 })),
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
}

function renderEditor(props: Record<string, unknown> = {}) {
  return import("@/features/tags/RecordTagEditor").then(({ RecordTagEditor }) => {
    render(
        createElement(
          MantineProvider,
          { env: "test" },
          createElement(RecordTagEditor, {
          fieldLabel: "Add a tag",
          title: "Tags",
          description: "Tags organize this record.",
          emptyLabel: "No tags",
          removeLabel: (name: string) => `Remove ${name}`,
          tags: [],
          tagRevision: 1,
          ...props,
        }),
      ),
    );
  });
}

describe("RecordTagEditor", () => {
  beforeEach(() => {
    stubDomApis();
    vi.clearAllMocks();
    vi.mocked(listTags).mockResolvedValue({ items: [], total: 0, limit: 8, offset: 0 });
  });

  afterEach(() => {
    cleanup();
  });

  it("commits the typed name on Enter when nothing is highlighted", async () => {
    await renderEditor();

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });

    expect(screen.getByRole("button", { name: "Remove Books" }).textContent).not.toContain(
      "Remove Books",
    );
    expect(screen.getByText("Books")).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
  });

  it("shows a saved tag as its name and a pending name with New", async () => {
    await renderEditor({ tags: [{ id: "tag_ledger", name: "Ledger" }] });

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });

    const ledger = screen.getByText("Ledger");
    expect(ledger.textContent).toBe("Ledger");
    expect(ledger.closest(".mantine-Badge-root")?.textContent).toBe("Ledger");
    expect(screen.getByText("New").closest(".mantine-Badge-root")?.textContent).toContain("Books");
    expect(screen.getByRole("button", { name: "Remove Ledger" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Books" })).toBeTruthy();
  });

  it("adds a vocabulary tag when its option is clicked", async () => {
    vi.mocked(listTags).mockResolvedValue({
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
    });
    await renderEditor();

    fireEvent.change(screen.getByRole("textbox", { name: "Add a tag" }), {
      target: { value: "Led" },
    });
    fireEvent.click(await screen.findByRole("option", { name: "Ledger" }));

    expect(screen.getByText("Ledger").closest(".mantine-Badge-root")?.textContent).toBe("Ledger");
    expect(screen.queryByText("New")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove Ledger" })).toBeTruthy();
    expect(listTags).toHaveBeenCalledWith({
      q: "Led",
      limit: 8,
      signal: expect.any(AbortSignal),
    });
  });

  it("hides options already chosen by id or pending by name", async () => {
    vi.mocked(listTags).mockResolvedValue({
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
        {
          id: "tag_books",
          name: "books",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
        {
          id: "tag_shelf",
          name: "Shelf",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 3,
      limit: 8,
      offset: 0,
    });
    await renderEditor({ tags: [{ id: "tag_ledger", name: "Ledger" }] });

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.change(field, { target: { value: "s" } });

    expect(await screen.findByRole("option", { name: "Shelf" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Ledger" })).toBeNull();
    expect(screen.queryByRole("option", { name: "books" })).toBeNull();
  });

  it("adds the highlighted option on Enter instead of the typed text", async () => {
    vi.mocked(listTags).mockResolvedValue({
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
        {
          id: "tag_shelf",
          name: "Shelf",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 2,
      limit: 8,
      offset: 0,
    });
    await renderEditor();

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Led" } });
    await screen.findByRole("option", { name: "Ledger" });
    fireEvent.keyDown(field, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.keyDown(field, { key: "Enter", code: "Enter" });

    expect(screen.getByText("Ledger").closest(".mantine-Badge-root")?.textContent).toBe("Ledger");
    expect(screen.queryByText("New")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
  });

  it("shows a lookup failure beside the field instead of an empty list", async () => {
    vi.mocked(listTags).mockRejectedValue(new Error("offline"));
    await renderEditor();

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Led" } });

    expect(
      await screen.findByText(
        "Couldn't look up tags. You can still save the name you typed.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("option")).toBeNull();

    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByRole("button", { name: "Remove Led" })).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
  });

  it("commits the typed name on Enter when a failed lookup drops the highlight", async () => {
    vi.mocked(listTags)
      .mockResolvedValueOnce({
        items: [
          {
            id: "tag_ledger",
            name: "Ledger",
            description: null,
            created_at: "2026-09-10T04:00:00Z",
            updated_at: "2026-09-10T04:00:00Z",
          },
        ],
        total: 1,
        limit: 8,
        offset: 0,
      })
      .mockRejectedValueOnce(new Error("offline"));
    await renderEditor();

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Led" } });
    await screen.findByRole("option", { name: "Ledger" });
    fireEvent.keyDown(field, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.change(field, { target: { value: "Books" } });

    expect(
      await screen.findByText(
        "Couldn't look up tags. You can still save the name you typed.",
      ),
    ).toBeTruthy();
    fireEvent.keyDown(field, { key: "Enter", code: "Enter" });

    expect(screen.getByRole("button", { name: "Remove Books" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Ledger" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
  });

  it("shows an in-flight lookup inside the listbox", async () => {
    let resolveSearch: (page: {
      items: {
        id: string;
        name: string;
        description: null;
        created_at: string;
        updated_at: string;
      }[];
      total: number;
      limit: number;
      offset: number;
    }) => void = () => {};
    vi.mocked(listTags).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSearch = resolve;
        }),
    );
    await renderEditor();

    fireEvent.change(screen.getByRole("textbox", { name: "Add a tag" }), {
      target: { value: "Led" },
    });

    const searching = await screen.findByText("Looking up tags");
    expect(searching.closest("[role='listbox']")).toBeTruthy();

    resolveSearch({
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
    });

    expect(await screen.findByRole("option", { name: "Ledger" })).toBeTruthy();
    expect(screen.queryByText("Looking up tags")).toBeNull();
  });

  it("keeps the ten-tag limit visible and still saves an eleventh name", async () => {
    const onSave = vi.fn(async () => undefined);
    const tags = Array.from({ length: 10 }, (_, index) => ({
      id: `tag_${index}`,
      name: `Tag ${index}`,
    }));
    await renderEditor({ tags, saveLabel: "Save tags", onSave });

    expect(screen.getByText("A record can carry ten tags.")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Add a tag" }), {
      target: { value: "Extra" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save tags" }));

    expect(onSave).toHaveBeenCalledWith({
      tag_ids: tags.map((tag) => tag.id),
      names: ["Extra"],
    });
    expect(screen.getByText("A record can carry ten tags.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Extra" })).toBeTruthy();
  });

  it("disables save when the field is empty and the set matches the loaded assignment", async () => {
    await renderEditor({
      tags: [{ id: "tag_ledger", name: "Ledger" }],
      saveLabel: "Save tags",
    });

    const save = screen.getByRole("button", { name: "Save tags" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(save.getAttribute("data-variant")).toBe("light");

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "   " } });
    expect(save.disabled).toBe(true);

    fireEvent.change(field, { target: { value: "Books" } });
    expect(save.disabled).toBe(false);

    fireEvent.change(field, { target: { value: "" } });
    expect(save.disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Remove Ledger" }));
    expect(save.disabled).toBe(false);
  });

  it("clears the query and closes suggestions on Escape without changing chosen tags", async () => {
    vi.mocked(listTags).mockResolvedValue({
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
    });
    await renderEditor({ tags: [{ id: "tag_kept", name: "Kept" }] });

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Led" } });
    expect(await screen.findByRole("option", { name: "Ledger" })).toBeTruthy();
    fireEvent.keyDown(field, { key: "Escape" });

    expect((field as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("option", { name: "Ledger" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove Kept" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Ledger" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
  });

  it("removes the last pending name, otherwise the last chosen tag, on Backspace in an empty field", async () => {
    await renderEditor({ tags: [{ id: "tag_ledger", name: "Ledger" }] });

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByRole("button", { name: "Remove Books" })).toBeTruthy();

    fireEvent.change(field, { target: { value: "x" } });
    fireEvent.keyDown(field, { key: "Backspace" });
    expect(screen.getByRole("button", { name: "Remove Books" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Ledger" })).toBeTruthy();

    fireEvent.change(field, { target: { value: "" } });
    fireEvent.keyDown(field, { key: "Backspace" });
    expect(screen.queryByRole("button", { name: "Remove Books" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove Ledger" })).toBeTruthy();

    fireEvent.keyDown(field, { key: "Backspace" });
    expect(screen.queryByRole("button", { name: "Remove Ledger" })).toBeNull();
  });
});
