import type { NodeExecution } from "@/features/channels/types";

/** For nodes cannot be pinned because their loop state cannot be replayed safely. */
export const FOR_NODE_TYPE = "volume.for";

export type EditorPin = {
  node_id: string;
  output: unknown;
};

export type EditorNodePhase = "succeeded" | "failed" | "pinned" | "dead";

const FAILED_STATUS = new Set(["failed", "cancelled"]);

export function canPinNode(nodeType: string): boolean {
  return nodeType !== FOR_NODE_TYPE;
}

/**
 * Nodes missing from `executions` were outside the stop closure or not reached.
 * A failed or cancelled record wins; skipped counts as succeeded.
 */
export function editorPhaseByNode(
  nodeIds: readonly string[],
  executions: readonly Pick<NodeExecution, "seq" | "node_id" | "status">[],
): Map<string, EditorNodePhase> {
  const grouped = new Map<string, Pick<NodeExecution, "seq" | "status">[]>();
  for (const item of executions) {
    const list = grouped.get(item.node_id) ?? [];
    list.push(item);
    grouped.set(item.node_id, list);
  }
  const phases = new Map<string, EditorNodePhase>();
  for (const id of nodeIds) {
    phases.set(id, phaseOf(grouped.get(id) ?? []));
  }
  return phases;
}

function phaseOf(
  items: readonly Pick<NodeExecution, "seq" | "status">[],
): EditorNodePhase {
  if (items.length === 0) return "dead";
  if (items.some((item) => FAILED_STATUS.has(item.status))) return "failed";
  const latest = items.reduce((best, item) => (item.seq >= best.seq ? item : best));
  if (latest.status === "pinned") return "pinned";
  return "succeeded";
}

export function pinStorageKey(channelId: string): string {
  return `refraq.channel.editor-pins.${channelId}`;
}

export function loadPins(storage: Storage, channelId: string): EditorPin[] {
  try {
    const raw = storage.getItem(pinStorageKey(channelId));
    if (!raw) return [];
    return normalizePins(JSON.parse(raw) as unknown);
  } catch {
    return [];
  }
}

export function savePins(storage: Storage, channelId: string, pins: readonly EditorPin[]): void {
  storage.setItem(pinStorageKey(channelId), JSON.stringify(pins));
}

export function normalizePins(value: unknown): EditorPin[] {
  if (!Array.isArray(value)) return [];
  const byId = new Map<string, EditorPin>();
  for (const item of value) {
    if (!isPin(item)) continue;
    byId.set(item.node_id, { node_id: item.node_id, output: item.output });
  }
  return [...byId.values()];
}

function isPin(value: unknown): value is EditorPin {
  if (value == null || typeof value !== "object" || !("node_id" in value) || !("output" in value)) {
    return false;
  }
  const nodeId = (value as { node_id: unknown }).node_id;
  return typeof nodeId === "string" && nodeId.length > 0;
}

/** Drop pins for nodes that are gone or are For nodes, which the endpoint rejects. */
export function pinsForGraph(
  pins: readonly EditorPin[],
  nodes: readonly { id: string; type: string }[],
): EditorPin[] {
  const allowed = new Set(
    nodes.filter((node) => canPinNode(node.type)).map((node) => node.id),
  );
  const kept: EditorPin[] = [];
  const seen = new Set<string>();
  for (const pin of normalizePins(pins)) {
    if (!allowed.has(pin.node_id) || seen.has(pin.node_id)) continue;
    seen.add(pin.node_id);
    kept.push(pin);
  }
  return kept;
}

export function withPin(pins: readonly EditorPin[], pin: EditorPin): EditorPin[] {
  return [...pins.filter((item) => item.node_id !== pin.node_id), pin];
}

export function withoutPin(pins: readonly EditorPin[], nodeId: string): EditorPin[] {
  return pins.filter((item) => item.node_id !== nodeId);
}
