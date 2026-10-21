"use client";

import { useEffect, useRef } from "react";

import { MOTION_MS } from "@/theme/tokens";

export type CanvasShortcutHandlers = {
  /** History keys no-op while the graph is locked. Viewport keys still run. */
  mutable: boolean;
  /** While an overlay is open, Tab keeps moving focus. */
  overlayOpen: boolean;
  undo: () => void;
  redo: () => void;
  fitView: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  zoomTo100: () => void;
  openHelp: () => void;
  selectAll: () => void;
  openPicker: () => void;
};

type ShortcutCommand =
  | "undo"
  | "redo"
  | "fit"
  | "zoomIn"
  | "zoomOut"
  | "zoom100"
  | "help"
  | "selectAll"
  | "openPicker";

/** Viewport buttons and keys share this duration. Reduced motion snaps. */
export function canvasViewportDuration(): number {
  const reduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reduced ? 0 : MOTION_MS.base;
}

export function useCanvasShortcuts(handlers: CanvasShortcutHandlers): void {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (!canvasShortcutTarget(event.target)) return;
      const command = matchCanvasShortcut(event);
      if (!command) return;
      const current = handlersRef.current;
      if ((command === "undo" || command === "redo") && !current.mutable) return;
      if (command === "openPicker" && (!current.mutable || current.overlayOpen)) return;
      event.preventDefault();
      if (command === "undo") current.undo();
      else if (command === "redo") current.redo();
      else if (command === "fit") current.fitView();
      else if (command === "zoomIn") current.zoomIn();
      else if (command === "zoomOut") current.zoomOut();
      else if (command === "zoom100") current.zoomTo100();
      else if (command === "selectAll") current.selectAll();
      else if (command === "openPicker") current.openPicker();
      else current.openHelp();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function canvasShortcutTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (!target.closest(".channel-canvas-stage")) return false;
  if (insideEditable(target)) return false;
  if (target.closest(".channel-node-config")) return false;
  if (target.closest(".mantine-Modal-root, [role='dialog']")) return false;
  return true;
}

function insideEditable(target: Element): boolean {
  return target.closest("input, textarea, [contenteditable='true'], [contenteditable='']") != null;
}

function matchCanvasShortcut(event: KeyboardEvent): ShortcutCommand | null {
  const mod = event.ctrlKey || event.metaKey;
  if (mod && event.code === "KeyZ") return event.shiftKey ? "redo" : "undo";
  if (mod && !event.shiftKey && event.code === "KeyY") return "redo";
  if (mod && !event.shiftKey && !event.altKey && event.code === "KeyA") return "selectAll";
  if (!mod && !event.altKey && !event.shiftKey && event.key === "Tab") return "openPicker";
  if (!mod && !event.altKey && event.shiftKey && event.code === "Digit1") return "fit";
  if (!mod && !event.altKey && event.key === "?") return "help";
  if (mod && !event.altKey && isZoomIn(event)) return "zoomIn";
  if (mod && !event.altKey && isZoomOut(event)) return "zoomOut";
  if (mod && !event.altKey && !event.shiftKey && isZoomReset(event)) return "zoom100";
  return null;
}

function isZoomIn(event: KeyboardEvent): boolean {
  return event.key === "=" || event.key === "+";
}

function isZoomOut(event: KeyboardEvent): boolean {
  return event.key === "-" || event.key === "_";
}

function isZoomReset(event: KeyboardEvent): boolean {
  return event.key === "0" || event.code === "Digit0";
}
