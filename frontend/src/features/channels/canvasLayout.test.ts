import { describe, expect, it } from "vitest";
import { canvasLayoutNode, materializeExecutionOrder } from "./canvasLayout";
import { emptyNodeData } from "./graphValidation";
import type { NodeTypeSpec } from "./types";
import type { GraphNode } from "./types";

const node = (id: string, y: number, execution_order?: number): GraphNode => ({ id, ref: id, name: id, type: "test", position: { x: 0, y }, config: {}, on_error: "stop", retry: null, ...(execution_order === undefined ? {} : { execution_order }) });

describe("materializeExecutionOrder", () => {
  it("uses measured visible ports and does not feed old frame dimensions back as minima", () => {
    const data = emptyNodeData("test", "test", "Test", {}, false, null);
    const spec = { inputs: [{ port: "main" }, { port: "loop" }], outputs: [{ port: "main" }, { port: "error" }] } as NodeTypeSpec;
    const leaf = { id: "leaf", position: { x: 0, y: 0 }, data, measured: { width: 300, height: 180 } };
    const input = canvasLayoutNode(leaf, spec, true);
    expect(input.inputs).toEqual([{ port: "main", offset: { x: 0, y: 90 } }]);
    expect(input.outputs?.[0].offset?.y).toBeCloseTo(60);
    expect(input.outputs?.[1].offset?.y).toBeCloseTo(120);
    expect(canvasLayoutNode(leaf, spec, false).outputs).toEqual([{ port: "main", offset: { x: 300, y: 90 } }]);
    const frame = canvasLayoutNode({ ...leaf, data: { ...data, container: { round_templates: [] } }, measured: { width: 50000, height: 50000 } }, spec, false, 100);
    expect(frame.width).toBeUndefined();
    expect(frame.height).toBeUndefined();
    expect(frame.headerHeight).toBe(100);
  });
  it("rejects exhausted exact integer capacity without changing explicit priorities", () => {
    const explicit = node("explicit", 0, Number.MAX_SAFE_INTEGER);
    expect(materializeExecutionOrder([explicit])).toEqual([explicit]);
    expect(() => materializeExecutionOrder([explicit, node("legacy", 1)])).toThrow(RangeError);
    const near = node("near", 0, Number.MAX_SAFE_INTEGER - 2);
    expect(materializeExecutionOrder([near, node("b", 2), node("a", 1)]).map((item) => item.execution_order)).toEqual([Number.MAX_SAFE_INTEGER - 2, Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER - 1]);
  });
  it("preserves explicit priorities and converts all legacy nodes after them before movement", () => {
    const nodes = [node("z", 20), node("explicit", 900, 7), node("b", 10), node("a", 10)];
    const result = materializeExecutionOrder(nodes);
    expect(result.map((item) => [item.id, item.execution_order])).toEqual([["z", 10], ["explicit", 7], ["b", 9], ["a", 8]]);
    expect(nodes[0].execution_order).toBeUndefined();
    expect(materializeExecutionOrder(result)).toEqual(result);
  });
});
