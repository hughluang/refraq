import { describe, expect, it } from "vitest";

import {
  clearPosition,
  frameBox,
  layoutNodePorts,
  parentsFirst,
} from "@/features/channels/portLayout";
import type { ContainerDeclaration } from "@/features/channels/types";

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

  it("places For each inset on the left of the frame facing right, and done on the right", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }, { port: "loop" }],
      [{ port: "each" }, { port: "done" }],
      { frame: true },
    );
    expect(laid.inputs.map((port) => [port.port, port.position, port.inset, port.labelled])).toEqual([
      ["main", "left", false, false],
    ]);
    expect(laid.outputs.map((port) => [port.port, port.position, port.inset, port.labelled])).toEqual([
      ["each", "right", true, true],
      ["done", "right", false, true],
    ]);
  });
});

const CATALOG = new Map<string, ContainerDeclaration | null>([
  ["lab.frame", { round_templates: [] }],
  ["volume.batch_read", { round_templates: [] }],
  ["volume.for", null],
  ["read.sql", null],
]);

function declared(nodeType: string): ContainerDeclaration | null {
  return CATALOG.get(nodeType) ?? null;
}

describe("frameBox", () => {
  const frame = (id: string, parentId?: string, position = { x: 0, y: 0 }) => ({
    id,
    parentId,
    position,
    container: declared("lab.frame"),
  });
  const card = (id: string, parentId: string, position: { x: number; y: number }) => ({
    id,
    parentId,
    position,
    container: declared("read.sql"),
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

  it("sizes a volume.for child as a card when the catalog declaration is null", () => {
    const nodes = [
      frame("outer"),
      {
        id: "walk",
        parentId: "outer",
        position: { x: 40, y: 48 },
        container: declared("volume.for"),
      },
    ];
    // 40 + 208 + 48 = 296 -> minimum 320; 48 + 56 + 48 = 152 -> minimum 180
    expect(frameBox("outer", nodes)).toEqual({ width: 320, height: 180 });
  });

  it("sizes a nested Batch Read as a frame inside an outer frame", () => {
    const nodes = [
      frame("outer"),
      {
        ...frame("batch", "outer", { x: 40, y: 48 }),
        container: declared("volume.batch_read"),
      },
      card("step", "batch", { x: 80, y: 40 }),
    ];
    // 80 + 208 + 48 = 336, 40 + 56 + 48 = 144 -> min height 180
    expect(frameBox("batch", nodes)).toEqual({ width: 336, height: 180 });
    // 40 + 336 + 48 = 424, 48 + 180 + 48 = 276
    expect(frameBox("outer", nodes)).toEqual({ width: 424, height: 276 });
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

describe("clearPosition", () => {
  const placed = { width: 208, height: 56 };
  const center = { x: 0, y: 0 };

  function overlaps(
    position: { x: number; y: number },
    item: { x: number; y: number; width: number; height: number },
  ) {
    return !(
      position.x + placed.width <= item.x ||
      item.x + item.width <= position.x ||
      position.y + placed.height <= item.y ||
      item.y + item.height <= position.y
    );
  }

  it("uses the first cell around the center when nothing is occupied", () => {
    expect(clearPosition(center, placed, [])).toEqual({ x: -270, y: -48 });
  });

  it("steps past a full neighborhood to the right of every occupied box", () => {
    const occupied = [{ x: -10000, y: -10000, width: 20000, height: 20000 }];
    const position = clearPosition(center, placed, occupied);
    expect(position).toEqual({ x: 10000, y: 0 });
    expect(occupied.some((item) => overlaps(position, item))).toBe(false);
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
