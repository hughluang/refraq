import { describe, expect, it } from "vitest";

import { layoutNodePorts, returnEdgePath } from "@/features/channels/portLayout";

describe("layoutNodePorts", () => {
  it("keeps a single main handle unlabelled on its side", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }],
      [{ port: "main" }, { port: "error" }],
    );
    expect(laid.inputs).toEqual([
      { port: "main", position: "left", top: "50%", labelled: false, loopBack: false },
    ]);
    expect(laid.outputs.map((port) => port.port)).toEqual(["main"]);
    expect(laid.outputs[0]?.labelled).toBe(false);
  });

  it("labels both If outputs and spaces them evenly", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }],
      [
        { port: "true", loop_back: false },
        { port: "false", loop_back: false },
      ],
    );
    expect(laid.outputs.map((port) => [port.port, port.top, port.labelled, port.loopBack])).toEqual([
      ["true", `${(1 / 3) * 100}%`, true, false],
      ["false", `${(2 / 3) * 100}%`, true, false],
    ]);
  });

  it("puts the For loop input on the bottom and marks each as a loop-back", () => {
    const laid = layoutNodePorts(
      [{ port: "main" }, { port: "loop" }],
      [
        { port: "each", loop_back: true },
        { port: "done", loop_back: false },
      ],
    );
    expect(laid.inputs.map((port) => [port.port, port.position, port.labelled])).toEqual([
      ["main", "left", false],
      ["loop", "bottom", true],
    ]);
    expect(laid.outputs.find((port) => port.port === "each")?.loopBack).toBe(true);
    expect(laid.outputs.find((port) => port.port === "done")?.labelled).toBe(true);
  });
});

describe("returnEdgePath", () => {
  it("bows below both ends", () => {
    const routed = returnEdgePath(240, 40, 80, 96);
    expect(routed.labelY).toBeGreaterThan(96);
    expect(routed.path).toContain(`${routed.labelY}`);
    expect(routed.path.endsWith("80,96")).toBe(true);
  });
});
