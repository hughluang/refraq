/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listTags } from "@/features/tags/api";

const LABELS: Record<string, string> = {
  "common.retry": "Retry",
  "tags.editor.searching": "Looking up tags",
  "tags.editor.searchFailed": "Couldn't look up tags. Try again.",
  "tags.editor.limitHint": "A record can carry at most ten tags.",
  "tags.editor.limitBlocked": "This record already has ten tags. Remove one, then add another.",
  "tags.editor.placeholder": "Search or type a new tag",
  "tags.editor.create": "Create tag “{{name}}”",
  "tags.editor.duplicate": "This tag is already on the record.",
  "tags.editor.unsaved": "Unsaved",
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

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });

    const books = screen.getByText("Books");
    const pending = books.closest(".mantine-Pill-root");
    expect(pending?.textContent).toContain("Books");
    expect(pending?.textContent).not.toContain("New");
    expect(pending?.hasAttribute("data-pending")).toBe(true);
    expect(screen.getByRole("button", { name: "Remove Books" }).textContent).not.toContain(
      "Remove Books",
    );
    expect(screen.queryByText("New")).toBeNull();
  });

  it("shows a saved tag as its name and a pending name without a status word", async () => {
    await renderEditor({ tags: [{ id: "tag_ledger", name: "Ledger" }] });

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });

    const ledger = screen.getByText("Ledger").closest(".mantine-Pill-root");
    expect(ledger?.textContent).toContain("Ledger");
    expect(ledger?.textContent).not.toContain("New");
    expect(ledger?.hasAttribute("data-pending")).toBe(false);
    const books = screen.getByText("Books").closest(".mantine-Pill-root");
    expect(books?.textContent).toContain("Books");
    expect(books?.hasAttribute("data-pending")).toBe(true);
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

    fireEvent.change(screen.getByRole("combobox", { name: "Tags" }), {
      target: { value: "Led" },
    });
    fireEvent.click(await screen.findByRole("option", { name: "Ledger" }));

    const ledger = screen.getByText("Ledger").closest(".mantine-Pill-root");
    expect(ledger?.textContent).toContain("Ledger");
    expect(ledger?.hasAttribute("data-pending")).toBe(false);
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

    const field = screen.getByRole("combobox", { name: "Tags" });
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

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Led" } });
    await screen.findByRole("option", { name: "Ledger" });
    fireEvent.keyDown(field, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.keyDown(field, { key: "Enter", code: "Enter" });

    const ledger = screen.getByText("Ledger").closest(".mantine-Pill-root");
    expect(ledger?.textContent).toContain("Ledger");
    expect(ledger?.hasAttribute("data-pending")).toBe(false);
    expect(screen.queryByText("New")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
  });

  it("shows a lookup failure in the list and does not create on Enter", async () => {
    vi.mocked(listTags).mockRejectedValue(new Error("offline"));
    await renderEditor();

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Led" } });

    const failed = await screen.findByText("Couldn't look up tags. Try again.");
    expect(failed.closest("[role='listbox']")).toBeTruthy();
    expect(screen.queryByRole("option")).toBeNull();

    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
    expect((field as HTMLInputElement).value).toBe("Led");

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
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("option", { name: "Ledger" })).toBeTruthy();
    expect(screen.queryByText("Couldn't look up tags. Try again.")).toBeNull();
  });

  it("does not commit a typed name on Enter after a failed lookup", async () => {
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

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Led" } });
    await screen.findByRole("option", { name: "Ledger" });
    fireEvent.keyDown(field, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.change(field, { target: { value: "Books" } });

    expect(await screen.findByText("Couldn't look up tags. Try again.")).toBeTruthy();
    fireEvent.keyDown(field, { key: "Enter", code: "Enter" });

    expect(screen.queryByRole("button", { name: "Remove Books" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Ledger" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();
    expect((field as HTMLInputElement).value).toBe("Books");
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

    fireEvent.change(screen.getByRole("combobox", { name: "Tags" }), {
      target: { value: "Led" },
    });

    const searching = await screen.findByText("Looking up tags");
    expect(searching.closest("[role='listbox']")).toBeTruthy();
    expect(screen.queryByRole("option")).toBeNull();
    await waitFor(() => {
      expect(listTags).toHaveBeenCalled();
    });

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

  it("refuses an eleventh name and leaves it in the field", async () => {
    const onSave = vi.fn(async () => undefined);
    const tags = Array.from({ length: 10 }, (_, index) => ({
      id: `tag_${index}`,
      name: `Tag ${index}`,
    }));
    await renderEditor({ tags, saveLabel: "Save tags", onSave });

    expect(screen.getByText("A record can carry at most ten tags.")).toBeTruthy();
    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Extra" } });
    expect(
      (await screen.findAllByText("This record already has ten tags. Remove one, then add another."))
        .length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("option", { name: "Create tag “Extra”" })).toBeNull();
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Save tags" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Remove Extra" })).toBeNull();
    expect((field as HTMLInputElement).value).toBe("Extra");
  });

  it("disables save when the field is empty and the set matches the loaded assignment", async () => {
    await renderEditor({
      tags: [{ id: "tag_ledger", name: "Ledger" }],
      saveLabel: "Save tags",
    });

    const save = screen.getByRole("button", { name: "Save tags" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(save.getAttribute("data-variant")).toBe("light");
    expect(screen.queryByText("Unsaved")).toBeNull();

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "   " } });
    expect(save.disabled).toBe(true);
    expect(screen.queryByText("Unsaved")).toBeNull();

    fireEvent.change(field, { target: { value: "Books" } });
    expect(save.disabled).toBe(false);
    expect(screen.getByText("Unsaved")).toBeTruthy();

    fireEvent.change(field, { target: { value: "" } });
    expect(save.disabled).toBe(true);
    expect(screen.queryByText("Unsaved")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove Ledger" }));
    expect(save.disabled).toBe(false);
  });

  it("closes suggestions on Escape, then clears the query on a second Escape", async () => {
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

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Led" } });
    expect(await screen.findByRole("option", { name: "Ledger" })).toBeTruthy();
    fireEvent.keyDown(field, { key: "Escape" });

    expect((field as HTMLInputElement).value).toBe("Led");
    expect(field.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("button", { name: "Remove Kept" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Ledger" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Led" })).toBeNull();

    fireEvent.keyDown(field, { key: "Escape" });
    expect((field as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("button", { name: "Remove Kept" })).toBeTruthy();
  });

  it("removes the last pending name, otherwise the last chosen tag, on Backspace in an empty field", async () => {
    await renderEditor({ tags: [{ id: "tag_ledger", name: "Ledger" }] });

    const field = screen.getByRole("combobox", { name: "Tags" });
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

  it("adds a pending tag from the create row after lookup", async () => {
    await renderEditor();

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.click(await screen.findByRole("option", { name: "Create tag “Books”" }));

    const books = screen.getByText("Books").closest(".mantine-Pill-root");
    expect(books?.hasAttribute("data-pending")).toBe(true);
    expect((field as HTMLInputElement).value).toBe("");
    expect(screen.queryByText("New")).toBeNull();
  });

  it("leaves a typed name in the field on blur", async () => {
    await renderEditor({ tags: [{ id: "tag_kept", name: "Kept" }] });

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.blur(field);

    expect((field as HTMLInputElement).value).toBe("Books");
    expect(screen.queryByRole("button", { name: "Remove Books" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove Kept" })).toBeTruthy();
  });

  it("does not add a second chip when the name is already chosen", async () => {
    await renderEditor({ tags: [{ id: "tag_books", name: "Books" }] });

    const field = screen.getByRole("combobox", { name: "Tags" });
    fireEvent.change(field, { target: { value: "books" } });

    expect(
      (await screen.findAllByText("This tag is already on the record.")).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("option", { name: "Create tag “books”" })).toBeNull();
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getAllByRole("button", { name: "Remove Books" })).toHaveLength(1);
    expect((field as HTMLInputElement).value).toBe("books");
  });
});
