/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RowActions, type RowActionVerb } from "@/components/display/RowActions";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const dictionary: Record<string, string> = {
      "common.rowActions.more": "More actions for {{record}}",
      "common.cancel": "Cancel",
      "common.confirm": "Confirm",
      "feedback.confirm.title": "Confirm {{record}}",
      "feedback.confirm.body": "{{record}}: {{consequence}} This cannot be undone.",
    };
    const template = dictionary[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
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

describe("RowActions", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps two verbs inline and the rest in a named overflow menu", () => {
    const onEdit = vi.fn();
    const onArchive = vi.fn();
    const verbs: RowActionVerb[] = [
      { key: "edit", label: "Edit", safety: "immediate", onClick: onEdit },
      {
        key: "publish",
        label: "Publish",
        safety: "confirm",
        onClick: vi.fn(),
      },
      { key: "archive", label: "Archive", safety: "immediate", onClick: onArchive },
      { key: "drop", label: "Drop", safety: "immediate", onClick: vi.fn(), hidden: true },
    ];
    render(shell(createElement(RowActions, { recordName: "Atlas", verbs })));

    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Publish" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(screen.queryByText("Drop")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "More actions for Atlas" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(onArchive).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("shows a disabled verb with its reason", async () => {
    const onDelete = vi.fn();
    const verbs: RowActionVerb[] = [
      {
        key: "delete",
        label: "Delete",
        color: "red",
        safety: "immediate",
        disabledReason: "Publish a version first",
        onClick: onDelete,
      },
    ];
    render(shell(createElement(RowActions, { recordName: "Atlas", verbs })));
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.click(button);
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.mouseEnter(button.parentElement ?? button);
    expect(await screen.findByText("Publish a version first")).toBeTruthy();
  });
});
