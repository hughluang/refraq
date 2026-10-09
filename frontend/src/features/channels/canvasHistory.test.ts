import { describe, expect, it } from "vitest";

import {
  createHistory,
  pushHistory,
  redoHistory,
  shouldCommitEdgeChanges,
  shouldCommitNodeChanges,
  undoHistory,
} from "@/features/channels/canvasHistory";

describe("shouldCommitNodeChanges", () => {
  it("skips selection, dimensions, and an in-progress drag", () => {
    expect(shouldCommitNodeChanges([{ type: "select" }])).toBe(false);
    expect(shouldCommitNodeChanges([{ type: "dimensions" }])).toBe(false);
    expect(shouldCommitNodeChanges([{ type: "position", dragging: true }])).toBe(false);
  });

  it("commits a finished drag, a removal, and a drag mixed with removal", () => {
    expect(shouldCommitNodeChanges([{ type: "position", dragging: false }])).toBe(true);
    expect(shouldCommitNodeChanges([{ type: "remove" }])).toBe(true);
    expect(
      shouldCommitNodeChanges([
        { type: "position", dragging: true },
        { type: "remove" },
      ]),
    ).toBe(true);
  });
});

describe("shouldCommitEdgeChanges", () => {
  it("skips selection and commits removal", () => {
    expect(shouldCommitEdgeChanges([{ type: "select" }])).toBe(false);
    expect(shouldCommitEdgeChanges([{ type: "remove" }])).toBe(true);
  });
});

describe("history", () => {
  it("undoes and redoes a single step", () => {
    const start = createHistory("a");
    const next = pushHistory(start, "b");
    expect(undoHistory(next).present).toBe("a");
    expect(redoHistory(undoHistory(next)).present).toBe("b");
    expect(undoHistory(start)).toBe(start);
  });
});