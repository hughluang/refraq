import { describe, expect, it } from "vitest";

import {
  ancestorIds,
  crossesFrame,
  edgesAfterReparent,
  frameLinkAllowed,
  placementFromPort,
  reparentDrop,
  type LinkEdge,
  type LinkMember,
} from "@/features/channels/frameLink";

function member(
  id: string,
  nodeType: string,
  position: { x: number; y: number },
  parentId?: string,
): LinkMember {
  return parentId ? { id, nodeType, position, parentId } : { id, nodeType, position };
}

function edge(id: string, source: string, target: string, sourceHandle: string): LinkEdge {
  return { id, source, target, sourceHandle };
}

const frame = (id: string, position: { x: number; y: number }, parentId?: string) =>
  member(id, "volume.for", position, parentId);

describe("crossesFrame", () => {
  it("treats an empty parent as none and allows a For to reach its own child", () => {
    expect(crossesFrame(undefined, undefined, "walk")).toBe(false);
    expect(crossesFrame("", null, "walk")).toBe(false);
    expect(crossesFrame(undefined, "walk", "walk")).toBe(false);
    expect(crossesFrame("walk", undefined, "step")).toBe(true);
    expect(crossesFrame("outer", "inner", "step")).toBe(true);
  });
});

describe("frameLinkAllowed", () => {
  const nodes = [
    frame("outer", { x: 0, y: 0 }),
    frame("inner", { x: 40, y: 48 }, "outer"),
    member("body", "read.sql", { x: 16, y: 16 }, "outer"),
    member("leaf", "read.sql", { x: 24, y: 24 }, "inner"),
    member("after", "read.sql", { x: 400, y: 40 }),
  ];

  it("allows each only onto a direct child and rejects every other way across a frame", () => {
    expect(frameLinkAllowed(nodes, { source: "inner", target: "leaf", sourceHandle: "each" })).toBe(true);
    expect(frameLinkAllowed(nodes, { source: "inner", target: "body", sourceHandle: "each" })).toBe(false);
    expect(frameLinkAllowed(nodes, { source: "inner", target: "leaf", sourceHandle: "done" })).toBe(false);
    expect(frameLinkAllowed(nodes, { source: "inner", target: "body", sourceHandle: "done" })).toBe(true);
    expect(frameLinkAllowed(nodes, { source: "body", target: "inner", sourceHandle: "main" })).toBe(true);
    expect(frameLinkAllowed(nodes, { source: "body", target: "leaf", sourceHandle: "main" })).toBe(false);
    expect(frameLinkAllowed(nodes, { source: "leaf", target: "inner", sourceHandle: "main" })).toBe(false);
    expect(frameLinkAllowed(nodes, { source: "after", target: "outer", sourceHandle: "main" })).toBe(true);
  });
});

describe("reparentDrop", () => {
  it("parents a node to the innermost frame and keeps its absolute position", () => {
    const outer = frame("outer", { x: 0, y: 0 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    const card = member("step", "read.sql", { x: 100, y: 100 });
    const [nextOuter, nextInner, nextStep] = reparentDrop([outer, inner, card], ["step"], { x: 50, y: 60 });
    expect(nextOuter).toEqual(outer);
    expect(nextInner).toEqual(inner);
    expect(nextStep).toEqual({ id: "step", nodeType: "read.sql", parentId: "inner", position: { x: 60, y: 52 } });
  });

  it("clears parent when the pointer leaves the frame measured without the dragged node", () => {
    const walk = frame("walk", { x: 0, y: 0 });
    const step = member("step", "read.sql", { x: 400, y: 400 }, "walk");
    const [nextWalk, nextStep] = reparentDrop([walk, step], ["step"], { x: 400, y: 100 });
    expect(nextWalk).toEqual(walk);
    expect(nextStep).toEqual({ id: "step", nodeType: "read.sql", position: { x: 400, y: 400 } });
    expect(nextStep).not.toHaveProperty("parentId");
  });

  it("does not drop into the dragged frame or its descendant", () => {
    const outer = frame("outer", { x: 0, y: 0 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    const [nextOuter, nextInner] = reparentDrop([outer, inner], ["outer"], { x: 50, y: 60 });
    expect(nextOuter).toEqual(outer);
    expect(nextInner).toEqual(inner);
  });

  it("leaves a child of a dragged frame parented to that frame", () => {
    const walk = frame("walk", { x: 16, y: 24 });
    const step = member("step", "read.sql", { x: 32, y: 40 }, "walk");
    const next = reparentDrop([walk, step], ["walk", "step"], { x: 800, y: 800 });
    expect(next.find((node) => node.id === "step")).toEqual(step);
    expect(next.find((node) => node.id === "walk")?.parentId).toBeUndefined();
  });
});

describe("edgesAfterReparent", () => {
  it("deletes each on the way out, done on the way in, and any edge that still crosses", () => {
    const walk = frame("walk", { x: 0, y: 0 });
    const step = member("step", "read.sql", { x: 32, y: 40 }, "walk");
    const after = member("after", "read.sql", { x: 480, y: 40 });
    const edges = [
      edge("each", "walk", "step", "each"),
      edge("leak", "step", "after", "main"),
      edge("feed", "after", "walk", "main"),
    ];
    const left = reparentDrop([walk, step, after], ["step"], { x: 480, y: 80 });
    expect(edgesAfterReparent(edges, left).map((item) => item.id)).toEqual(["leak", "feed"]);
    const outside = member("step", "read.sql", { x: 480, y: 40 });
    const entered = reparentDrop([walk, outside, after], ["step"], { x: 48, y: 48 });
    const enteredEdges = [
      edge("done", "walk", "step", "done"),
      edge("into", "after", "step", "main"),
      edge("feed", "after", "walk", "main"),
    ];
    expect(edgesAfterReparent(enteredEdges, entered).map((item) => item.id)).toEqual(["feed"]);
  });
});

describe("ancestorIds", () => {
  const nodes = [
    member("trigger", "trigger.manual", { x: 0, y: 0 }),
    frame("loop", { x: 40, y: 0 }),
    member("body", "read.sql", { x: 32, y: 40 }, "loop"),
    member("later", "read.sql", { x: 48, y: 40 }, "loop"),
    member("after", "read.sql", { x: 400, y: 40 }),
  ];
  const edges = [
    edge("to-loop", "trigger", "loop", "main"),
    edge("each", "loop", "body", "each"),
    edge("next", "body", "later", "main"),
    edge("back", "body", "loop", "main"),
    edge("done", "loop", "after", "done"),
    edge("leak", "later", "after", "main"),
  ];

  it("includes the For and its upstream inside the body and stops at the frame", () => {
    expect([...ancestorIds("body", edges, nodes)].sort()).toEqual(["loop", "trigger"]);
    expect([...ancestorIds("later", edges, nodes)].sort()).toEqual(["body", "loop", "trigger"]);
    expect([...ancestorIds("after", edges, nodes)].sort()).toEqual(["loop", "trigger"]);
  });
});

describe("placementFromPort", () => {
  const walk = frame("walk", { x: 40, y: 40 });

  it("puts an each card inside the frame and leaves a done card outside", () => {
    expect(placementFromPort([walk], "walk", "each", { x: 80, y: 88 })).toEqual({
      parentId: "walk",
      position: { x: 40, y: 48 },
    });
    expect(placementFromPort([walk], "walk", "each", { x: 400, y: 40 })).toEqual({
      parentId: "walk",
      position: { x: 48, y: 48 },
    });
    expect(placementFromPort([walk], "walk", "done", { x: 480, y: 40 })).toEqual({
      position: { x: 480, y: 40 },
    });
    expect(placementFromPort([walk], "walk", "done", { x: 200, y: 80 })).toEqual({
      position: { x: 432, y: 40 },
    });
    expect(placementFromPort([walk], "walk", "main", { x: 200, y: 80 })).toEqual({
      position: { x: 200, y: 80 },
    });
  });
});
