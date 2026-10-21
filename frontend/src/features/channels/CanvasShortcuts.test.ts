/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasShortcuts, CANVAS_SHORTCUTS } from "@/features/channels/CanvasShortcuts";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) =>
    (
      {
        "channels.canvas.shortcuts": "Keyboard shortcuts",
        "channels.canvas.shortcuts.group.edit": "Edit",
        "channels.canvas.shortcuts.group.view": "View",
        "channels.canvas.undo": "Undo",
        "channels.canvas.redo": "Redo",
        "channels.canvas.shortcuts.delete": "Delete selection",
        "channels.canvas.shortcuts.open": "Open settings",
        "channels.canvas.shortcuts.close": "Close overlay",
        "channels.canvas.fitView": "Fit view",
        "channels.canvas.zoomIn": "Zoom in",
        "channels.canvas.zoomOut": "Zoom out",
        "channels.canvas.zoom100": "100%",
        "channels.canvas.shortcuts.help": "Show keyboard shortcuts",
      } as Record<string, string>
    )[key] ?? key,
}));

const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)";
const WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)";

function renderHelp(userAgent: string, opened = true) {
  const onClose = vi.fn();
  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(CanvasShortcuts, { opened, onClose, userAgent }),
    ),
  );
  return onClose;
}

describe("CanvasShortcuts", () => {
  beforeEach(() => {
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
  });

  it("lists only the shortcuts that work, grouped into edit and view", () => {
    const ids = CANVAS_SHORTCUTS.map((row) => row.id);
    expect(ids).toEqual([
      "undo",
      "redo",
      "delete",
      "open",
      "close",
      "fit",
      "zoomIn",
      "zoomOut",
      "zoom100",
      "help",
    ]);
    expect(new Set(CANVAS_SHORTCUTS.map((row) => row.group))).toEqual(new Set(["edit", "view"]));

    renderHelp(WINDOWS);
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(withinText(dialog, "Edit")).toBe(true);
    expect(withinText(dialog, "View")).toBe(true);
    expect(dialog.textContent).toContain("Ctrl+Z");
    expect(dialog.textContent).toContain("Ctrl+Shift+Z");
    expect(dialog.textContent).toContain("Ctrl+Y");
    expect(dialog.textContent).toContain("Delete");
    expect(dialog.textContent).toContain("Backspace");
    expect(dialog.textContent).toContain("Enter");
    expect(dialog.textContent).toContain("Escape");
    expect(dialog.textContent).toContain("Shift+1");
    expect(dialog.textContent).toContain("Ctrl+=");
    expect(dialog.textContent).toContain("Ctrl+-");
    expect(dialog.textContent).toContain("Ctrl+0");
    expect(dialog.textContent).toContain("?");
    expect(dialog.textContent).not.toContain("⌘");
  });

  it("shows the command modifier on macOS", () => {
    renderHelp(MAC);
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(dialog.textContent).toContain("⌘Z");
    expect(dialog.textContent).toContain("⇧⌘Z");
    expect(dialog.textContent).toContain("⌘Y");
    expect(dialog.textContent).toContain("⌘=");
    expect(dialog.textContent).not.toContain("Ctrl+");
  });

  it("closes from Escape", () => {
    const onClose = renderHelp(WINDOWS);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("stays closed until asked", () => {
    renderHelp(WINDOWS, false);
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("documents that channel canvas shortcuts need canvas focus", () => {
    const doc = readFileSync(resolve(__dirname, "../../../../docs/ui-console-interaction.md"), "utf8");
    const section = doc.split(/^## 8\. /m)[0]?.split(/^### 7\.1 /m)[1] ?? "";
    expect(section).toMatch(/Channel canvas shortcuts/i);
    expect(section).toMatch(/only while focus is inside the channel canvas/i);
    expect(section).toMatch(/Shift\+1/);
    expect(section).toMatch(/Ctrl\+=/);
    expect(section).toMatch(/Ctrl\+Y/);
    expect(section).toMatch(/Delete or Backspace/);
    const motion = doc.split(/^## 8\. Motion/m)[1]?.split(/^## 9\. /m)[0] ?? "";
    expect(motion).toMatch(/That edge is the only canvas motion/);
  });
});

function withinText(element: HTMLElement, text: string): boolean {
  return (element.textContent ?? "").includes(text);
}
