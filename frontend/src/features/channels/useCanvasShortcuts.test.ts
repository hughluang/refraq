/** @vitest-environment jsdom */

import { cleanup, render } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  canvasViewportDuration,
  useCanvasShortcuts,
  type CanvasShortcutHandlers,
} from "@/features/channels/useCanvasShortcuts";

function handlers(overrides: Partial<CanvasShortcutHandlers> = {}): CanvasShortcutHandlers {
  return {
    mutable: true,
    overlayOpen: false,
    undo: vi.fn(),
    redo: vi.fn(),
    fitView: vi.fn(),
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    zoomTo100: vi.fn(),
    openHelp: vi.fn(),
    selectAll: vi.fn(),
    openPicker: vi.fn(),
    copy: vi.fn(),
    cut: vi.fn(),
    duplicate: vi.fn(),
    paste: vi.fn(),
    ...overrides,
  };
}

function Host({
  api,
  outside = false,
}: {
  api: CanvasShortcutHandlers;
  outside?: boolean;
}) {
  useCanvasShortcuts(api);
  const stage = createElement(
    "div",
    { className: "channel-canvas-stage" },
    createElement("button", { type: "button" }, "Stage"),
    createElement("input", { "aria-label": "Name" }),
    createElement(
      "div",
      { className: "channel-node-config" },
      createElement("button", { type: "button" }, "Settings"),
    ),
    createElement(
      "div",
      { className: "mantine-Modal-root", role: "dialog" },
      createElement("button", { type: "button" }, "Dialog"),
    ),
  );
  if (!outside) return stage;
  return createElement("div", null, stage, createElement("button", { type: "button" }, "Outside"));
}

function press(target: Element, init: KeyboardEventInit): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

function pasteOn(target: Element, text: string): Event {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", {
    value: { getData: () => text },
  });
  target.dispatchEvent(event);
  return event;
}

function buttonNamed(name: string): HTMLButtonElement {
  const found = [...document.querySelectorAll("button")].find((item) => item.textContent === name);
  if (!(found instanceof HTMLButtonElement)) throw new Error(`missing ${name}`);
  return found;
}

describe("useCanvasShortcuts", () => {
  afterEach(() => {
    cleanup();
  });

  it("undoes and redoes from the canvas and ignores those keys while editing is locked", () => {
    const api = handlers();
    const view = render(createElement(Host, { api }));
    const stage = buttonNamed("Stage");

    const undo = press(stage, { key: "z", code: "KeyZ", ctrlKey: true });
    expect(undo.defaultPrevented).toBe(true);
    expect(api.undo).toHaveBeenCalledTimes(1);

    press(stage, { key: "z", code: "KeyZ", metaKey: true, shiftKey: true });
    press(stage, { key: "y", code: "KeyY", ctrlKey: true });
    expect(api.redo).toHaveBeenCalledTimes(2);

    view.rerender(createElement(Host, { api: handlers({ ...api, mutable: false }) }));
    const locked = press(buttonNamed("Stage"), { key: "z", code: "KeyZ", ctrlKey: true });
    expect(locked.defaultPrevented).toBe(false);
    expect(api.undo).toHaveBeenCalledTimes(1);
  });

  it("fits and zooms from the canvas and blocks the browser shortcut", () => {
    const api = handlers();
    render(createElement(Host, { api }));
    const stage = buttonNamed("Stage");

    const fit = press(stage, { key: "!", code: "Digit1", shiftKey: true });
    const zoomIn = press(stage, { key: "=", code: "Equal", ctrlKey: true });
    const zoomInPlus = press(stage, { key: "+", code: "Equal", metaKey: true, shiftKey: true });
    const zoomOut = press(stage, { key: "-", code: "Minus", ctrlKey: true });
    const zoom100 = press(stage, { key: "0", code: "Digit0", metaKey: true });
    const help = press(stage, { key: "?" });
    const selectAll = press(stage, { key: "a", code: "KeyA", ctrlKey: true });
    const selectAllMac = press(stage, { key: "a", code: "KeyA", metaKey: true });

    expect(fit.defaultPrevented).toBe(true);
    expect(zoomIn.defaultPrevented).toBe(true);
    expect(zoomInPlus.defaultPrevented).toBe(true);
    expect(zoomOut.defaultPrevented).toBe(true);
    expect(zoom100.defaultPrevented).toBe(true);
    expect(help.defaultPrevented).toBe(true);
    expect(selectAll.defaultPrevented).toBe(true);
    expect(selectAllMac.defaultPrevented).toBe(true);
    expect(api.fitView).toHaveBeenCalledTimes(1);
    expect(api.zoomIn).toHaveBeenCalledTimes(2);
    expect(api.zoomOut).toHaveBeenCalledTimes(1);
    expect(api.zoomTo100).toHaveBeenCalledTimes(1);
    expect(api.openHelp).toHaveBeenCalledTimes(1);
    expect(api.selectAll).toHaveBeenCalledTimes(2);
  });

  it("opens the node picker from Tab unless an overlay is open or the graph is locked", () => {
    const api = handlers();
    const view = render(createElement(Host, { api }));
    const stage = buttonNamed("Stage");

    const tab = press(stage, { key: "Tab" });
    expect(tab.defaultPrevented).toBe(true);
    expect(api.openPicker).toHaveBeenCalledTimes(1);

    const shiftTab = press(stage, { key: "Tab", shiftKey: true });
    expect(shiftTab.defaultPrevented).toBe(false);
    expect(api.openPicker).toHaveBeenCalledTimes(1);

    view.rerender(createElement(Host, { api: handlers({ ...api, overlayOpen: true }) }));
    const overlaid = press(buttonNamed("Stage"), { key: "Tab" });
    expect(overlaid.defaultPrevented).toBe(false);
    expect(api.openPicker).toHaveBeenCalledTimes(1);

    view.rerender(createElement(Host, { api: handlers({ ...api, mutable: false }) }));
    const locked = press(buttonNamed("Stage"), { key: "Tab" });
    expect(locked.defaultPrevented).toBe(false);
    expect(api.openPicker).toHaveBeenCalledTimes(1);
  });

  it("ignores viewport and history keys in fields, the settings panel, a modal, and outside the canvas", () => {
    const api = handlers();
    render(createElement(Host, { api, outside: true }));

    const name = document.querySelector("input");
    if (!(name instanceof HTMLInputElement)) throw new Error("missing input");
    for (const init of [
      { key: "!", code: "Digit1", shiftKey: true },
      { key: "0", code: "Digit0", ctrlKey: true },
      { key: "=", code: "Equal", ctrlKey: true },
      { key: "-", code: "Minus", metaKey: true },
      { key: "?" },
      { key: "z", code: "KeyZ", ctrlKey: true },
      { key: "y", code: "KeyY", ctrlKey: true },
      { key: "a", code: "KeyA", ctrlKey: true },
      { key: "a", code: "KeyA", metaKey: true },
      { key: "c", code: "KeyC", ctrlKey: true },
      { key: "x", code: "KeyX", metaKey: true },
      { key: "d", code: "KeyD", ctrlKey: true },
      { key: "Tab" },
    ] satisfies KeyboardEventInit[]) {
      const event = press(name, init);
      expect(event.defaultPrevented).toBe(false);
    }
    const pasted = pasteOn(name, "{\"kind\":\"refraq.channel.fragment\"}");
    expect(pasted.defaultPrevented).toBe(false);

    const settings = press(buttonNamed("Settings"), { key: "!", code: "Digit1", shiftKey: true });
    const dialog = press(buttonNamed("Dialog"), { key: "?", code: "Slash", shiftKey: true });
    const dialogSelect = press(buttonNamed("Dialog"), { key: "a", code: "KeyA", metaKey: true });
    const outside = press(buttonNamed("Outside"), { key: "0", code: "Digit0", ctrlKey: true });
    expect(settings.defaultPrevented).toBe(false);
    expect(dialog.defaultPrevented).toBe(false);
    expect(dialogSelect.defaultPrevented).toBe(false);
    expect(outside.defaultPrevented).toBe(false);
    expect(api.fitView).not.toHaveBeenCalled();
    expect(api.zoomIn).not.toHaveBeenCalled();
    expect(api.zoomOut).not.toHaveBeenCalled();
    expect(api.zoomTo100).not.toHaveBeenCalled();
    expect(api.openHelp).not.toHaveBeenCalled();
    expect(api.undo).not.toHaveBeenCalled();
    expect(api.redo).not.toHaveBeenCalled();
    expect(api.selectAll).not.toHaveBeenCalled();
    expect(api.openPicker).not.toHaveBeenCalled();
    expect(api.copy).not.toHaveBeenCalled();
    expect(api.cut).not.toHaveBeenCalled();
    expect(api.duplicate).not.toHaveBeenCalled();
    expect(api.paste).not.toHaveBeenCalled();
  });

  it("copies even while locked, and ignores cut, duplicate, and paste until the graph can change", () => {
    const api = handlers();
    const view = render(createElement(Host, { api }));
    const stage = buttonNamed("Stage");

    const copy = press(stage, { key: "c", code: "KeyC", ctrlKey: true });
    const cut = press(stage, { key: "x", code: "KeyX", metaKey: true });
    const duplicate = press(stage, { key: "d", code: "KeyD", ctrlKey: true });
    const pasted = pasteOn(stage, "{\"nodes\":[]}");

    expect(copy.defaultPrevented).toBe(true);
    expect(cut.defaultPrevented).toBe(true);
    expect(duplicate.defaultPrevented).toBe(true);
    expect(pasted.defaultPrevented).toBe(true);
    expect(api.copy).toHaveBeenCalledTimes(1);
    expect(api.cut).toHaveBeenCalledTimes(1);
    expect(api.duplicate).toHaveBeenCalledTimes(1);
    expect(api.paste).toHaveBeenCalledWith("{\"nodes\":[]}");

    view.rerender(createElement(Host, { api: handlers({ ...api, mutable: false }) }));
    const lockedCut = press(buttonNamed("Stage"), { key: "x", code: "KeyX", ctrlKey: true });
    const lockedDuplicate = press(buttonNamed("Stage"), { key: "d", code: "KeyD", ctrlKey: true });
    const lockedPaste = pasteOn(buttonNamed("Stage"), "{\"nodes\":[1]}");
    const lockedCopy = press(buttonNamed("Stage"), { key: "c", code: "KeyC", metaKey: true });

    expect(lockedCut.defaultPrevented).toBe(true);
    expect(lockedDuplicate.defaultPrevented).toBe(true);
    expect(lockedPaste.defaultPrevented).toBe(true);
    expect(lockedCopy.defaultPrevented).toBe(true);
    expect(api.cut).toHaveBeenCalledTimes(1);
    expect(api.duplicate).toHaveBeenCalledTimes(1);
    expect(api.paste).toHaveBeenCalledTimes(1);
    expect(api.copy).toHaveBeenCalledTimes(2);
  });

  it("uses a 200ms viewport transition and skips it when motion is reduced", () => {
    expect(canvasViewportDuration()).toBe(200);
    const original = window.matchMedia;
    window.matchMedia = (query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    });
    try {
      expect(canvasViewportDuration()).toBe(0);
    } finally {
      window.matchMedia = original;
    }
  });
});
