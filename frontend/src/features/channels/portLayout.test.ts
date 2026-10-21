import { describe, expect, it } from "vitest";

import { frameBox, layoutNodePorts, parentsFirst } from "@/features/channels/portLayout";

describe("layoutNodePorts", () => {
  it("keeps a single main handle unlabelled on its side", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }],
      [{ port: "main" }, { port: "error" }],
    );
    expect(laid.inputs).toEqual([
      { port: "main", position: "left", top: "50%", labelled: false, inset: false },
    ]);
    expect(laid.outputs.map((port) => port.port)).toEqual(["main"]);
    expect(laid.outputs[0]?.labelled).toBe(false);
    expect(laid.outputs[0]?.inset).toBe(false);
  });

  it("labels both If outputs and spaces them evenly", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }],
      [{ port: "true" }, { port: "false" }],
    );
    expect(laid.outputs.map((port) => [port.port, port.top, port.labelled, port.inset])).toEqual([
      ["true", `${(1 / 3) * 100}%`, true, false],
      ["false", `${(2 / 3) * 100}%`, true, false],
    ]);
  });

  it("drops the loop input instead of placing it on the bottom", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }, { port: "loop" }],
      [{ port: "main" }],
    );
    expect(laid.inputs.map((port) => [port.port, port.position])).toEqual([["main", "left"]]);
    expect(laid.outputs.map((port) => port.position)).toEqual(["right"]);
  });

  it("places For each inside the left of the frame and done on the right", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }, { port: "loop" }],
      [{ port: "each" }, { port: "done" }],
      { frame: true },
    );
    expect(laid.inputs.map((port) => [port.port, port.position, port.inset, port.labelled])).toEqual([
      ["main", "left", false, false],
    ]);
    expect(laid.outputs.map((port) => [port.port, port.position, port.inset, port.labelled])).toEqual([
      ["each", "left", true, true],
      ["done", "right", false, true],
    ]);
  });
});

describe("frameBox", () => {
  const frame = (id: string, parentId?: string, position = { x: 0, y: 0 }) => ({
    id,
    parentId,
    position,
    nodeType: "volume.for",
  });
  const card = (id: string, parentId: string, position: { x: number; y: number }) => ({
    id,
    parentId,
    position,
    nodeType: "read.sql",
  });

  it("uses a minimum size when a For has no children", () => {
    expect(frameBox("walk", [frame("walk")])).toEqual({ width: 320, height: 180 });
  });

  it("grows past a child card by a trailing margin", () => {
    // 80 + 208 + 48 = 336, 100 + 56 + 48 = 204
    expect(
      frameBox("walk", [frame("walk"), card("step", "walk", { x: 80, y: 100 })]),
    ).toEqual({ width: 336, height: 204 });
  });

  it("sizes an outer frame from the inner frame, not from the card inside it", () => {
    // Inner card at (200, 200): 200+208+48 = 456 wide, 200+56+48 = 304 tall.
    // Outer sees that frame at (40, 48): 40+456+48 = 544, 48+304+48 = 400.
    const nodes = [
      frame("outer"),
      frame("inner", "outer", { x: 40, y: 48 }),
      card("step", "inner", { x: 200, y: 200 }),
    ];
    expect(frameBox("inner", nodes)).toEqual({ width: 456, height: 304 });
    expect(frameBox("outer", nodes)).toEqual({ width: 544, height: 400 });
  });
});

describe("parentsFirst", () => {
  it("lists an outer For before the nested frame and its body", () => {
    const ordered = parentsFirst([
      { id: "body", parentId: "inner" },
      { id: "after" },
      { id: "inner", parentId: "outer" },
      { id: "outer" },
    ]);
    expect(ordered.map((node) => node.id)).toEqual(["after", "outer", "inner", "body"]);
  });
});
