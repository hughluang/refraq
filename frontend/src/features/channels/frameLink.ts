/** For-frame linking: which edges may cross, where a drag belongs, and which ancestors stay visible. */

import {
  CARD_HEIGHT,
  CARD_WIDTH,
  FRAME_PAD,
  frameBox,
} from "@/features/channels/portLayout";
import type { ContainerDeclaration } from "@/features/channels/types";

/** Gap kept between a For frame and a node created from `done` when the drop overlaps the frame. */
const DONE_OUTSIDE_GAP = 72;

export type LinkMember = {
  id: string;
  parentId?: string;
  position: { x: number; y: number };
  /** Copied from flow node data. `null` is not a Container. */
  container: ContainerDeclaration | null;
};

export type LinkEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
};

type Point = { x: number; y: number };

function none(parent: string | null | undefined): string | null {
  return parent ? parent : null;
}

/** True when the endpoints sit in different frames and the source is not the target's parent. */
export function crossesFrame(
  sourceParent: string | null | undefined,
  targetParent: string | null | undefined,
  sourceId: string,
): boolean {
  const source = none(sourceParent);
  const target = none(targetParent);
  if (source === target) return false;
  return target !== sourceId;
}

export function frameLinkAllowed(
  nodes: readonly {
    id: string;
    parentId?: string | null;
    container: ContainerDeclaration | null;
  }[],
  connection: { source?: string | null; target?: string | null; sourceHandle?: string | null },
): boolean {
  if (!connection.source || !connection.target) return false;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const source = byId.get(connection.source);
  const target = byId.get(connection.target);
  if (!source || !target) return false;
  if (crossesFrame(source.parentId, target.parentId, source.id)) return false;
  if (source.container == null) return true;
  const targetParent = none(target.parentId);
  if (connection.sourceHandle === "each") return targetParent === source.id;
  return targetParent !== source.id;
}

/** A For rect in flow space, captured when a drag starts and kept for the whole gesture. */
export type FrozenFrame = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

/** Frame rects from the membership committed at drag start. */
export function freezeFrames(members: readonly LinkMember[]): FrozenFrame[] {
  const byId = index(members);
  return members.flatMap((node) => {
    if (node.container == null) return [];
    const origin = absoluteOf(node, byId);
    const box = frameBox(node.id, members);
    return [{ id: node.id, x: origin.x, y: origin.y, width: box.width, height: box.height }];
  });
}

/**
 * Provisional parents for `draggedIds`. Each dragged node's center is tested against `frozen`.
 * The deepest containing frame wins. A child of a dragged frame keeps its parent.
 * Position is rewritten only when the parent changes, and the absolute position stays put.
 */
export function reparentDrag(
  members: readonly LinkMember[],
  draggedIds: readonly string[],
  frozen: readonly FrozenFrame[],
): LinkMember[] {
  const dragged = new Set(draggedIds);
  const byId = index(members);
  const excluded = (id: string) => dragged.has(id) || under(id, dragged, byId);
  return members.map((node) => {
    if (!dragged.has(node.id) || under(node.id, dragged, byId)) return node;
    const target = innermostFrozen(frozen, centerOf(node, members, byId), excluded, byId);
    if (none(node.parentId) === target) return node;
    const absolute = absoluteOf(node, byId);
    const frame = target ? byId.get(target) : undefined;
    if (!frame) {
      return { id: node.id, container: node.container, position: absolute };
    }
    const origin = absoluteOf(frame, byId);
    return {
      id: node.id,
      container: node.container,
      parentId: frame.id,
      position: { x: absolute.x - origin.x, y: absolute.y - origin.y },
    };
  });
}

export function edgesAfterReparent<E extends LinkEdge>(
  edges: readonly E[],
  nodes: readonly {
    id: string;
    parentId?: string | null;
    container: ContainerDeclaration | null;
  }[],
): E[] {
  return edges.filter((edge) =>
    frameLinkAllowed(nodes, {
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
    }),
  );
}

export function ancestorIds(
  nodeId: string,
  edges: readonly { source: string; target: string }[],
  nodes: readonly { id: string; parentId?: string | null }[],
): Set<string> {
  const parents = new Map(nodes.map((node) => [node.id, node.parentId]));
  const incoming = new Map<string, string[]>();
  for (const edge of edges) {
    if (crossesFrame(parents.get(edge.source), parents.get(edge.target), edge.source)) continue;
    const list = incoming.get(edge.target) ?? [];
    list.push(edge.source);
    incoming.set(edge.target, list);
  }
  const seen = new Set<string>();
  const stack = [...(incoming.get(nodeId) ?? [])];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    stack.push(...(incoming.get(current) ?? []));
  }
  return seen;
}

/** Top-left in flow space, including nested frame origins. */
export function absolutePosition(members: readonly LinkMember[], id: string): Point | null {
  const byId = index(members);
  const node = byId.get(id);
  if (!node) return null;
  return absoluteOf(node, byId);
}

/**
 * Position and parent for a node created from a port. `absolute` is in flow space.
 * `each` parents the card to that For. Every other port inherits the source parent.
 * `done` is pushed clear of its For, then expressed in the parent frame.
 */
export function placementFromPort(
  members: readonly LinkMember[],
  sourceId: string,
  sourceHandle: string | null | undefined,
  absolute: Point,
): { parentId?: string; position: Point } {
  const byId = index(members);
  const source = byId.get(sourceId);
  if (!source) return { position: { x: absolute.x, y: absolute.y } };
  if (source.container != null && sourceHandle === "each") {
    const origin = absoluteOf(source, byId);
    const box = frameBox(source.id, members);
    const relative = { x: absolute.x - origin.x, y: absolute.y - origin.y };
    const inside =
      relative.x >= 0 &&
      relative.y >= 0 &&
      relative.x + CARD_WIDTH <= box.width &&
      relative.y + CARD_HEIGHT <= box.height;
    return {
      parentId: source.id,
      position: inside ? relative : { x: FRAME_PAD, y: FRAME_PAD },
    };
  }
  let flow = { x: absolute.x, y: absolute.y };
  if (source.container != null && sourceHandle === "done") {
    const origin = absoluteOf(source, byId);
    const box = frameBox(source.id, members);
    const card = { x: absolute.x, y: absolute.y, width: CARD_WIDTH, height: CARD_HEIGHT };
    const rect = { x: origin.x, y: origin.y, width: box.width, height: box.height };
    if (overlaps(card, rect)) {
      flow = { x: origin.x + box.width + DONE_OUTSIDE_GAP, y: origin.y };
    }
  }
  return relativeToParent(source, flow, byId);
}

/** Parent and position for a node inserted on an edge. The midpoint is in flow space. */
export function placementOnEdge(
  members: readonly LinkMember[],
  sourceId: string,
  targetId: string,
  sourceHandle: string | null | undefined,
): { parentId?: string; position: Point } | null {
  const byId = index(members);
  const source = byId.get(sourceId);
  const target = byId.get(targetId);
  if (!source || !target) return null;
  const sourceAt = absoluteOf(source, byId);
  const targetAt = absoluteOf(target, byId);
  return placementFromPort(members, sourceId, sourceHandle, {
    x: (sourceAt.x + targetAt.x) / 2,
    y: (sourceAt.y + targetAt.y) / 2,
  });
}

function relativeToParent(
  source: LinkMember,
  flow: Point,
  byId: ReadonlyMap<string, LinkMember>,
): { parentId?: string; position: Point } {
  const parentId = none(source.parentId);
  const parent = parentId ? byId.get(parentId) : undefined;
  if (!parent) return { position: flow };
  const origin = absoluteOf(parent, byId);
  return {
    parentId: parent.id,
    position: { x: flow.x - origin.x, y: flow.y - origin.y },
  };
}

function index(members: readonly LinkMember[]): Map<string, LinkMember> {
  return new Map(members.map((node) => [node.id, node]));
}

function absoluteOf(node: LinkMember, byId: ReadonlyMap<string, LinkMember>, seen = new Set<string>()): Point {
  const parentId = none(node.parentId);
  const parent = parentId ? byId.get(parentId) : undefined;
  if (!parent || seen.has(node.id)) return { x: node.position.x, y: node.position.y };
  seen.add(node.id);
  const origin = absoluteOf(parent, byId, seen);
  return { x: origin.x + node.position.x, y: origin.y + node.position.y };
}

function under(id: string, dragged: ReadonlySet<string>, byId: ReadonlyMap<string, LinkMember>): boolean {
  const seen = new Set<string>();
  let current = none(byId.get(id)?.parentId);
  while (current && !seen.has(current)) {
    if (dragged.has(current)) return true;
    seen.add(current);
    const parent = byId.get(current);
    current = none(parent?.parentId);
  }
  return false;
}

function centerOf(
  node: LinkMember,
  members: readonly LinkMember[],
  byId: ReadonlyMap<string, LinkMember>,
): Point {
  const origin = absoluteOf(node, byId);
  const box =
    node.container != null
      ? frameBox(node.id, members)
      : { width: CARD_WIDTH, height: CARD_HEIGHT };
  return { x: origin.x + box.width / 2, y: origin.y + box.height / 2 };
}

function innermostFrozen(
  frozen: readonly FrozenFrame[],
  center: Point,
  excluded: (id: string) => boolean,
  byId: ReadonlyMap<string, LinkMember>,
): string | null {
  let chosen: string | null = null;
  let depth = -1;
  for (const frame of frozen) {
    if (excluded(frame.id)) continue;
    const inside =
      center.x >= frame.x &&
      center.x <= frame.x + frame.width &&
      center.y >= frame.y &&
      center.y <= frame.y + frame.height;
    if (!inside) continue;
    const nextDepth = chainDepth(frame.id, byId);
    if (nextDepth <= depth) continue;
    chosen = frame.id;
    depth = nextDepth;
  }
  return chosen;
}

function chainDepth(id: string, byId: ReadonlyMap<string, LinkMember>): number {
  let depth = 0;
  const seen = new Set<string>();
  let current = none(byId.get(id)?.parentId);
  while (current && byId.has(current) && !seen.has(current)) {
    seen.add(current);
    depth += 1;
    current = none(byId.get(current)?.parentId);
  }
  return depth;
}

function overlaps(
  left: { x: number; y: number; width: number; height: number },
  right: { x: number; y: number; width: number; height: number },
): boolean {
  return (
    left.x < right.x + right.width &&
    left.x + left.width > right.x &&
    left.y < right.y + right.height &&
    left.y + left.height > right.y
  );
}
