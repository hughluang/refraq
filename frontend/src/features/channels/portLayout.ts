/** Canvas placement for catalog ports. `loop` is the return input of a loop node. */

export const LOOP_RETURN_PORT = "loop";

export type HandleSide = "left" | "right" | "bottom";

export type PortPlacement = {
  port: string;
  position: HandleSide;
  /** Percentage from the top. Unused for a bottom handle. */
  top: string;
  /** Shown when this side has several handles, or the port is not `main`. */
  labelled: boolean;
  loopBack: boolean;
};

type PortLike = { port: string; loop_back?: boolean };

export function layoutNodePorts(
  inputs: readonly PortLike[],
  outputs: readonly PortLike[],
): { inputs: PortPlacement[]; outputs: PortPlacement[] } {
  const forward = inputs.filter((port) => port.port !== LOOP_RETURN_PORT);
  const returns = inputs.filter((port) => port.port === LOOP_RETURN_PORT);
  return {
    inputs: [...place(forward, "left"), ...place(returns, "bottom")],
    outputs: place(
      outputs.filter((port) => port.port !== "error"),
      "right",
    ),
  };
}

/** A return into `loop` bows under the nodes instead of crossing back through them. */
export function returnEdgePath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
): { path: string; labelX: number; labelY: number } {
  const dip = Math.max(sourceY, targetY) + 56;
  return {
    path: `M${sourceX},${sourceY} C${sourceX},${dip} ${targetX},${dip} ${targetX},${targetY}`,
    labelX: (sourceX + targetX) / 2,
    labelY: dip,
  };
}

export function isLoopReturn(port: string | null | undefined): boolean {
  return port === LOOP_RETURN_PORT;
}

function place(ports: readonly PortLike[], position: HandleSide): PortPlacement[] {
  const labelledSide = ports.length > 1;
  return ports.map((port, index) => ({
    port: port.port,
    position,
    top: `${((index + 1) / (ports.length + 1)) * 100}%`,
    labelled: position === "bottom" || labelledSide || port.port !== "main",
    loopBack: Boolean(port.loop_back),
  }));
}
