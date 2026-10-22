import { describe, expect, it } from "vitest";

import {
  absolutePosition,
  ancestorIds,
  crossesFrame,
  edgesAfterReparent,
  frameLinkAllowed,
  freezeFrames,
  placementFromPort,
  placementOnEdge,
  reparentDrag,
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

describe("reparentDrag", () => {
  it("parents a node to the innermost frozen frame and keeps its absolute position", () => {
    const outer = frame("outer", { x: 0, y: 0 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    const card = member("step", "read.sql", { x: 100, y: 100 });
    const members = [outer, inner, card];
    const [nextOuter, nextInner, nextStep] = reparentDrag(members, ["step"], freezeFrames(members));
    expect(freezeFrames(members)).toEqual([
      { id: "outer", x: 0, y: 0, width: 408, height: 276 },
      { id: "inner", x: 40, y: 48, width: 320, height: 180 },
    ]);
    expect(nextOuter).toEqual(outer);
    expect(nextInner).toEqual(inner);
    expect(nextStep).toEqual({ id: "step", nodeType: "read.sql", parentId: "inner", position: { x: 60, y: 52 } });
  });

  it("keeps a child that grew the frame when its center stays inside the frozen rect", () => {
    const walk = frame("walk", { x: 0, y: 0 });
    const step = member("step", "read.sql", { x: 400, y: 400 }, "walk");
    const frozen = freezeFrames([walk, step]);
    expect(frozen).toEqual([{ id: "walk", x: 0, y: 0, width: 656, height: 504 }]);
    const nudged = member("step", "read.sql", { x: 420, y: 400 }, "walk");
    const [nextWalk, nextStep] = reparentDrag([walk, nudged], ["step"], frozen);
    expect(nextWalk).toEqual(walk);
    expect(nextStep).toEqual(nudged);
  });

  it("clears parent when the center leaves the frozen frame", () => {
    const walk = frame("walk", { x: 0, y: 0 });
    const step = member("step", "read.sql", { x: 400, y: 400 }, "walk");
    const frozen = freezeFrames([walk, step]);
    const moved = member("step", "read.sql", { x: 700, y: 400 }, "walk");
    const [nextWalk, nextStep] = reparentDrag([walk, moved], ["step"], frozen);
    expect(nextWalk).toEqual(walk);
    expect(nextStep).toEqual({ id: "step", nodeType: "read.sql", position: { x: 700, y: 400 } });
    expect(nextStep).not.toHaveProperty("parentId");
  });

  it("leaves a card outside when only its corner overlaps the frozen frame", () => {
    const walk = frame("walk", { x: 0, y: 0 });
    const step = member("step", "read.sql", { x: 220, y: 40 });
    const members = [walk, step];
    const [nextWalk, nextStep] = reparentDrag(members, ["step"], freezeFrames(members));
    expect(nextWalk).toEqual(walk);
    expect(nextStep).toEqual(step);
  });

  it("promotes a child to the outer frame when its center leaves the inner one", () => {
    const outer = frame("outer", { x: 0, y: 0 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    const step = member("step", "read.sql", { x: 16, y: 16 }, "inner");
    const frozen = freezeFrames([outer, inner, step]);
    const moved = member("step", "read.sql", { x: 236, y: 24 }, "inner");
    const next = reparentDrag([outer, inner, moved], ["step"], frozen);
    expect(next.find((node) => node.id === "step")).toEqual({
      id: "step",
      nodeType: "read.sql",
      parentId: "outer",
      position: { x: 276, y: 72 },
    });
  });

  it("does not drop into the dragged frame or its descendant", () => {
    const outer = frame("outer", { x: 0, y: 0 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    const members = [outer, inner];
    const [nextOuter, nextInner] = reparentDrag(members, ["outer"], freezeFrames(members));
    expect(nextOuter).toEqual(outer);
    expect(nextInner).toEqual(inner);
  });

  it("leaves a child of a dragged frame parented to that frame", () => {
    const walk = frame("walk", { x: 16, y: 24 });
    const step = member("step", "read.sql", { x: 32, y: 40 }, "walk");
    const members = [walk, step];
    const next = reparentDrag(members, ["walk", "step"], freezeFrames(members));
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
    const frozen = freezeFrames([walk, step, after]);
    const left = reparentDrag(
      [walk, member("step", "read.sql", { x: 480, y: 40 }, "walk"), after],
      ["step"],
      frozen,
    );
    expect(edgesAfterReparent(edges, left).map((item) => item.id)).toEqual(["leak", "feed"]);
    const outside = member("step", "read.sql", { x: 480, y: 40 });
    const parked = [walk, outside, after];
    const entered = reparentDrag(
      [walk, member("step", "read.sql", { x: 48, y: 48 }), after],
      ["step"],
      freezeFrames(parked),
    );
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

  it("leaves a top-level node where it was dropped", () => {
    const start = member("start", "trigger.manual", { x: 16, y: 24 });
    expect(placementFromPort([start], "start", "main", { x: 296, y: 24 })).toEqual({
      position: { x: 296, y: 24 },
    });
  });

  it("puts a card added from a child on the same frame, in that frame's coordinates", () => {
    const outer = frame("outer", { x: 10, y: 20 });
    const walk = frame("walk", { x: 100, y: 80 }, "outer");
    const step = member("step", "read.sql", { x: 40, y: 50 }, "walk");
    expect(placementFromPort([outer, walk, step], "step", "main", { x: 430, y: 150 })).toEqual({
      parentId: "walk",
      position: { x: 320, y: 50 },
    });
  });

  it("keeps an each card inside a nested frame", () => {
    const outer = frame("outer", { x: 100, y: 80 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    expect(placementFromPort([outer, inner], "inner", "each", { x: 200, y: 180 })).toEqual({
      parentId: "inner",
      position: { x: 60, y: 52 },
    });
  });

  it("places a nested done card in the outer frame, clear of the inner frame", () => {
    const grand = frame("grand", { x: 10, y: 20 });
    const outer = frame("outer", { x: 100, y: 80 }, "grand");
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    expect(placementFromPort([grand, outer, inner], "inner", "done", { x: 220, y: 180 })).toEqual({
      parentId: "outer",
      position: { x: 432, y: 48 },
    });
    expect(placementFromPort([grand, outer, inner], "inner", "main", { x: 220, y: 180 })).toEqual({
      parentId: "outer",
      position: { x: 110, y: 80 },
    });
  });
});

describe("absolutePosition", () => {
  it("adds each parent origin, including a frame nested inside a frame", () => {
    const outer = frame("outer", { x: 10, y: 20 });
    const inner = frame("inner", { x: 30, y: 40 }, "outer");
    const leaf = member("leaf", "read.sql", { x: 5, y: 7 }, "inner");
    const members = [outer, inner, leaf];
    expect(absolutePosition(members, "outer")).toEqual({ x: 10, y: 20 });
    expect(absolutePosition(members, "inner")).toEqual({ x: 40, y: 60 });
    expect(absolutePosition(members, "leaf")).toEqual({ x: 45, y: 67 });
    expect(absolutePosition(members, "missing")).toBeNull();
  });
});

describe("placementOnEdge", () => {
  it("uses the absolute midpoint and keeps a top-level insert at the top level", () => {
    const left = member("left", "read.sql", { x: 20, y: 40 });
    const right = member("right", "read.sql", { x: 300, y: 40 });
    expect(placementOnEdge([left, right], "left", "right", "main")).toEqual({
      position: { x: 160, y: 40 },
    });
  });

  it("inserts on an each edge inside the frame", () => {
    const walk = frame("walk", { x: 100, y: 40 });
    const step = member("step", "read.sql", { x: 80, y: 60 }, "walk");
    expect(placementOnEdge([walk, step], "walk", "step", "each")).toEqual({
      parentId: "walk",
      position: { x: 40, y: 30 },
    });
  });

  it("inserts on a nested done edge outside the inner frame and inside the outer one", () => {
    const outer = frame("outer", { x: 100, y: 80 });
    const inner = frame("inner", { x: 40, y: 48 }, "outer");
    const after = member("after", "read.sql", { x: 480, y: 40 }, "outer");
    expect(placementOnEdge([outer, inner, after], "inner", "after", "done")).toEqual({
      parentId: "outer",
      position: { x: 432, y: 48 },
    });
  });
});
