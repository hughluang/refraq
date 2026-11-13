import { describe, expect, it } from "vitest";

import { layoutGraph, LAYOUT_HEADER_HEIGHT, type LayoutNode, type LayoutPlacement } from "@/features/channels/graphLayout";
import { CARD_HEIGHT, CARD_WIDTH, FRAME_MIN_HEIGHT, FRAME_MIN_WIDTH } from "@/features/channels/portLayout";

function edge(id: string, source: string, target: string, port = "main") {
  return { id, source: { node_id: source, port }, target: { node_id: target, port: "main" } };
}

function expectGeometry(nodes: LayoutPlacement[]) {
  for (const node of nodes) {
    for (const value of [node.position.x, node.position.y, node.width, node.height]) {
      expect(Number.isFinite(value)).toBe(true);
    }
    const parent = nodes.find((item) => item.id === node.parent);
    if (parent) {
      expect(node.position.x).toBeGreaterThanOrEqual(48);
      expect(node.position.y).toBeGreaterThanOrEqual(LAYOUT_HEADER_HEIGHT);
      expect(node.position.x + node.width + 48).toBeLessThanOrEqual(parent.width);
      expect(node.position.y + node.height + 48).toBeLessThanOrEqual(parent.height);
    }
    for (const sibling of nodes) {
      if (sibling.id === node.id || (sibling.parent || null) !== (node.parent || null)) continue;
      expect(node.position.x + node.width <= sibling.position.x ||
        sibling.position.x + sibling.width <= node.position.x ||
        node.position.y + node.height <= sibling.position.y ||
        sibling.position.y + sibling.height <= node.position.y).toBe(true);
    }
  }
}

// The ticket-approved seam is topology + geometry -> placement, using the real engine.
describe("layoutGraph", () => {
  it("places a measured chain rightward without mutating its authored geometry", async () => {
    const nodes = [
      { id: "start", position: { x: -900, y: 700 }, width: 260, height: 110, inputs: [],
        outputs: [{ port: "main", offset: { x: 260, y: 80 } }] },
      { id: "end", position: { x: -900, y: 700 }, width: 340, height: 140, outputs: [],
        inputs: [{ port: "main", offset: { x: 0, y: 30 } }] },
    ];
    const edges = [{ id: "edge", source: { node_id: "start", port: "main" }, target: { node_id: "end", port: "main" } }];
    const before = structuredClone({ nodes, edges });
    const result = await layoutGraph({ nodes, edges });
    expect(result.status).toBe("laid-out");
    const start = result.nodes.find((node) => node.id === "start")!;
    const end = result.nodes.find((node) => node.id === "end")!;
    expect(start.width).toBe(260);
    expect(end.height).toBe(140);
    expect(end.position.x).toBeGreaterThanOrEqual(start.position.x + start.width + 48);
    expect({ nodes, edges }).toEqual(before);
    // Exact semantic offsets affect placement, rather than only port names.
    expect(start.position.y + 80).toBe(end.position.y + 30);
  });

  it("packs branches and joins with stable semantic output order", async () => {
    const nodes = [
      { id: "branch", inputs: [], outputs: [{ port: "true" }, { port: "false" }, { port: "error" }] },
      { id: "yes", height: 160, inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
      { id: "no", width: 380, inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
      { id: "failure", inputs: [{ port: "main" }], outputs: [] },
      { id: "join", inputs: [{ port: "main" }], outputs: [] },
      { id: "isolated", inputs: [], outputs: [] },
    ];
    const edges = [edge("t", "branch", "yes", "true"), edge("f", "branch", "no", "false"),
      edge("e", "branch", "failure", "error"), edge("yj", "yes", "join"), edge("nj", "no", "join")];
    const result = await layoutGraph({ nodes, edges });
    expectGeometry(result.nodes);
    const get = (id: string) => result.nodes.find((node) => node.id === id)!;
    expect(get("yes").position.y).toBeLessThan(get("no").position.y);
    expect(get("no").position.y).toBeLessThan(get("failure").position.y);
    expect(get("join").position.x).toBeGreaterThan(get("no").position.x + get("no").width);
    expect(await layoutGraph({ nodes: [...nodes].reverse(), edges: [...edges].reverse() })).toEqual(result);
    expect(await layoutGraph({ nodes: result.nodes.map((placed) => ({ ...nodes.find((node) => node.id === placed.id)!, position: placed.position })), edges })).toEqual(result);
  });

  it("sizes disconnected mixed nested containers bottom-up and preserves every membership", async () => {
    const nodes: LayoutNode[] = [
      { id: "for", container: { round_templates: [] }, inputs: [], outputs: [{ port: "each" }, { port: "done" }] },
      { id: "batch", parent: "for", container: { round_templates: [] }, inputs: [{ port: "main" }], outputs: [{ port: "each" }, { port: "done" }] },
      { id: "until", parent: "batch", container: { round_templates: ["until"] }, inputs: [{ port: "main" }], outputs: [{ port: "each" }, { port: "done" }] },
      { id: "leaf", parent: "until", width: 420, height: 190, inputs: [{ port: "main" }], outputs: [] },
      { id: "batchEnd", parent: "batch", inputs: [{ port: "main" }], outputs: [] },
      { id: "forEnd", parent: "for", inputs: [{ port: "main" }], outputs: [] },
      { id: "rootEnd", inputs: [{ port: "main" }], outputs: [] },
      { id: "empty", container: {}, inputs: [], outputs: [] },
      { id: "disconnected", parent: "for", height: 230, inputs: [], outputs: [] },
    ];
    const edges = [edge("fb", "for", "batch", "each"), edge("bu", "batch", "until", "each"),
      edge("ul", "until", "leaf", "each"), edge("ud", "until", "batchEnd", "done"),
      edge("bd", "batch", "forEnd", "done"), edge("fd", "for", "rootEnd", "done")];
    const before = structuredClone({ nodes, edges });
    const result = await layoutGraph({ nodes, edges });
    expect(result.status).toBe("laid-out");
    expectGeometry(result.nodes);
    expect(result.nodes.map(({ id, parent }) => ({ id, parent }))).toEqual(
      [...nodes].sort((a, b) => a.id < b.id ? -1 : 1).map(({ id, parent }) => ({ id, parent })),
    );
    expect(result.nodes.find((node) => node.id === "empty")).toMatchObject({ width: 320, height: 180 });
    expect(await layoutGraph({ nodes: [...nodes].reverse(), edges: [...edges].reverse() })).toEqual(result);
    expect({ nodes, edges }).toEqual(before);
  });

  it("keeps invalid parent drafts untouched rather than repairing or dropping nodes", async () => {
    const drafts: LayoutNode[][] = [
      [{ id: "orphan", parent: "missing", position: { x: -60, y: 45 }, width: 400, height: 210, inputs: [], outputs: [] }],
      [{ id: "card", inputs: [], outputs: [] }, { id: "child", parent: "card", inputs: [], outputs: [] }],
      [{ id: "a", container: {}, parent: "b", inputs: [], outputs: [] }, { id: "b", container: {}, parent: "a", inputs: [], outputs: [] }, { id: "other", inputs: [], outputs: [] }],
      [{ id: "self", container: {}, parent: "self", inputs: [], outputs: [] }],
    ];
    for (const nodes of drafts) {
      const before = structuredClone(nodes);
      const result = await layoutGraph({ nodes, edges: [] });
      expect(result.status).toBe("invalid-parent");
      expect(result.nodes).toHaveLength(nodes.length);
      for (const node of nodes) {
        expect(result.nodes.find((item) => item.id === node.id)).toEqual({
          id: node.id, ...(node.parent !== undefined ? { parent: node.parent } : {}),
          position: node.position ?? { x: 0, y: 0 },
          width: node.width ?? (node.container != null ? FRAME_MIN_WIDTH : CARD_WIDTH),
          height: node.height ?? (node.container != null ? FRAME_MIN_HEIGHT : CARD_HEIGHT),
        });
      }
      expect(nodes).toEqual(before);
    }
  });

  it("handles cyclic edges, self loops and unresolved drafts without deleting topology", async () => {
    const nodes = [
      { id: "a", inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
      { id: "b", inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
      { id: "c", inputs: [], outputs: [] },
    ];
    const validEdges = [edge("ab", "a", "b"), edge("ba", "b", "a"), edge("aa", "a", "a")];
    const edges = [...validEdges, edge("missing", "a", "absent"), edge("missingSource", "absent", "a"), edge("port", "a", "c")];
    const before = structuredClone({ nodes, edges });
    const result = await layoutGraph({ nodes, edges });
    expect(result.status).toBe("laid-out");
    expectGeometry(result.nodes);
    expect(result).toEqual(await layoutGraph({ nodes, edges: validEdges }));
    expect({ nodes, edges }).toEqual(before);
  });

  it("excludes illegal frame edges but still lays out every draft node", async () => {
    const nodes = [
      { id: "frame", container: {}, inputs: [], outputs: [{ port: "each" }, { port: "done" }] },
      { id: "child", parent: "frame", inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
      { id: "root", inputs: [{ port: "main" }], outputs: [] },
    ];
    const edges = [edge("cross", "child", "root"), edge("wrongEntry", "frame", "child", "done"),
      edge("wrongEach", "frame", "root", "each")];
    const result = await layoutGraph({ nodes, edges });
    expect(result.status).toBe("laid-out");
    expectGeometry(result.nodes);
    expect(result).toEqual(await layoutGraph({ nodes, edges: [] }));
  });

  it("reserves measured frame headers and frame minimums independently from card measurements", async () => {
    const nodes = [{ id: "frame", container: {}, width: 100, height: 90, headerHeight: 120, inputs: [], outputs: [{ port: "each" }] },
      { id: "child", parent: "frame", width: 210, height: 80, inputs: [{ port: "main" }], outputs: [] },
      { id: "empty", container: {}, width: 100, height: 90, inputs: [], outputs: [] }];
    const result = await layoutGraph({ nodes, edges: [edge("each", "frame", "child", "each")] });
    expect(result.nodes.find((node) => node.id === "child")!.position.y).toBeGreaterThanOrEqual(120);
    expect(result.nodes.find((node) => node.id === "empty")).toMatchObject({ width: 320, height: 180 });
    expectGeometry(result.nodes);
  });

  it("excludes same-scope each edges and unknown handles from engine input", async () => {
    const nodes = [
      { id: "frame", container: {}, inputs: [{ port: "main" }], outputs: [{ port: "each" }, { port: "done" }] },
      { id: "child", parent: "frame", inputs: [{ port: "main" }], outputs: [] },
      { id: "root", inputs: [{ port: "main" }], outputs: [{ port: "main" }] },
    ];
    const validEdges = [edge("validEach", "frame", "child", "each"), edge("validDone", "frame", "root", "done")];
    const edges = [edge("sameScope", "frame", "root", "each"),
      edge("unknownSource", "frame", "root", "missing"),
      { ...edge("unknownTarget", "root", "frame"), target: { node_id: "frame", port: "missing" } },
      ...validEdges];
    const result = await layoutGraph({ nodes, edges });
    expect(result.status).toBe("laid-out");
    expectGeometry(result.nodes);
    expect(result).toEqual(await layoutGraph({ nodes, edges: validEdges }));
  });

  it("accepts empty graphs and rejects invalid measured dimensions instead of fake success", async () => {
    expect(await layoutGraph({ nodes: [], edges: [] })).toEqual({ status: "laid-out", nodes: [] });
    await expect(layoutGraph({ nodes: [{ id: "a", width: NaN, inputs: [], outputs: [] }], edges: [] })).rejects.toThrow("finite and positive");
  });
});
