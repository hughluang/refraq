/** Canvas placement for catalog ports and For frames. */

export const FOR_NODE_TYPE = "volume.for";

/** Card size used to grow a frame. Matches the channel node card. */
export const CARD_WIDTH = 208;
export const CARD_HEIGHT = 56;

/** Gap kept after the rightmost and bottommost direct child. */
export const FRAME_PAD = 48;
export const FRAME_MIN_WIDTH = 320;
export const FRAME_MIN_HEIGHT = 180;

/** `each` sits this far inside the left edge of a For frame. */
export const EACH_INSET = 20;

const LOOP_RETURN_PORT = "loop";
const EACH_PORT = "each";

export type HandleSide = "left" | "right";

export type PortPlacement = {
  port: string;
  position: HandleSide;
  /** Percentage from the top. */
  top: string;
  /** Shown when this side has several handles, or the port is not `main`. */
  labelled: boolean;
  /** Inside the frame, on the left. For `each`. */
  inset: boolean;
};

type PortLike = { port: string };

export function layoutNodePorts(
  inputs: readonly PortLike[],
  outputs: readonly PortLike[],
  options?: { frame?: boolean },
): { inputs: PortPlacement[]; outputs: PortPlacement[] } {
  const inputsLaid = place(
    inputs.filter((port) => port.port !== LOOP_RETURN_PORT),
    "left",
  );
  const visible = outputs.filter((port) => port.port !== "error");
  if (!options?.frame) {
    return { inputs: inputsLaid, outputs: place(visible, "right") };
  }
  return {
    inputs: inputsLaid,
    outputs: [
      ...place(
        visible.filter((port) => port.port === EACH_PORT),
        "left",
        true,
      ),
      ...place(
        visible.filter((port) => port.port !== EACH_PORT),
        "right",
      ),
    ],
  };
}

export type FrameMember = {
  id: string;
  parentId?: string;
  position: { x: number; y: number };
  nodeType: string;
};

/** Width and height of a For frame. Not stored on the graph. */
export function frameBox(id: string, nodes: readonly FrameMember[]): { width: number; height: number } {
  return measureFrame(id, nodes, new Set());
}

/** Ancestors before descendants. Nodes with the same depth keep their order. */
export function parentsFirst<T extends { id: string; parentId?: string }>(nodes: readonly T[]): T[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const depthOf = (id: string, trail: Set<string>): number => {
    const parentId = byId.get(id)?.parentId;
    if (!parentId || trail.has(id) || !byId.has(parentId)) return 0;
    trail.add(id);
    return 1 + depthOf(parentId, trail);
  };
  return [...nodes].sort((left, right) => depthOf(left.id, new Set()) - depthOf(right.id, new Set()));
}

function measureFrame(
  id: string,
  nodes: readonly FrameMember[],
  seen: Set<string>,
): { width: number; height: number } {
  if (seen.has(id)) return { width: FRAME_MIN_WIDTH, height: FRAME_MIN_HEIGHT };
  seen.add(id);
  let right = 0;
  let bottom = 0;
  let hasChild = false;
  for (const child of nodes) {
    if (child.parentId !== id) continue;
    hasChild = true;
    const size =
      child.nodeType === FOR_NODE_TYPE
        ? measureFrame(child.id, nodes, seen)
        : { width: CARD_WIDTH, height: CARD_HEIGHT };
    right = Math.max(right, child.position.x + size.width);
    bottom = Math.max(bottom, child.position.y + size.height);
  }
  const pad = hasChild ? FRAME_PAD : 0;
  return {
    width: Math.max(FRAME_MIN_WIDTH, right + pad),
    height: Math.max(FRAME_MIN_HEIGHT, bottom + pad),
  };
}

function place(
  ports: readonly PortLike[],
  position: HandleSide,
  inset = false,
): PortPlacement[] {
  const labelledSide = ports.length > 1;
  return ports.map((port, index) => ({
    port: port.port,
    position,
    top: `${((index + 1) / (ports.length + 1)) * 100}%`,
    labelled: labelledSide || port.port !== "main",
    inset,
  }));
}
