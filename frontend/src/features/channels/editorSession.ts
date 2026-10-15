import type { EditorNodeExecution } from "@/features/channels/types";

/** For nodes cannot be pinned; the editor endpoint rejects them. */
export const FOR_NODE_TYPE = "volume.for";

export const EDITOR_ROW_LIMIT = 100;
export const EDITOR_ROW_LIMIT_MIN = 1;
export const EDITOR_ROW_LIMIT_MAX = 1000;

export type EditorPin = {
  node_id: string;
  output: unknown;
};

export type EditorNodePhase = "succeeded" | "failed" | "pinned" | "dead";

export type DryRunSummary =
  | {
      kind: "write.entity";
      inserted: number;
      updated: number;
      unchanged: number;
      deleted: number;
      unmatched: number;
    }
  | {
      kind: "state.variable";
      applied: boolean;
    };

const FAILED_STATUS = new Set(["failed", "cancelled"]);

export function clampRowLimit(value: unknown): number {
  if (value == null || value === "") return EDITOR_ROW_LIMIT;
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(parsed)) return EDITOR_ROW_LIMIT;
  if (parsed < EDITOR_ROW_LIMIT_MIN) return EDITOR_ROW_LIMIT_MIN;
  if (parsed > EDITOR_ROW_LIMIT_MAX) return EDITOR_ROW_LIMIT_MAX;
  return parsed;
}

export function canPinNode(nodeType: string): boolean {
  return nodeType !== FOR_NODE_TYPE;
}

/**
 * Nodes missing from `executions` were outside the stop closure or not reached.
 * A failed or cancelled record wins; skipped counts as succeeded.
 */
export function editorPhaseByNode(
  nodeIds: readonly string[],
  executions: readonly Pick<EditorNodeExecution, "seq" | "node_id" | "status">[],
): Map<string, EditorNodePhase> {
  const grouped = new Map<string, Pick<EditorNodeExecution, "seq" | "status">[]>();
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
  items: readonly Pick<EditorNodeExecution, "seq" | "status">[],
): EditorNodePhase {
  if (items.length === 0) return "dead";
  if (items.some((item) => FAILED_STATUS.has(item.status))) return "failed";
  const latest = items.reduce((best, item) => (item.seq >= best.seq ? item : best));
  if (latest.status === "pinned") return "pinned";
  return "succeeded";
}

export function latestEditorExecution<T extends Pick<EditorNodeExecution, "seq" | "node_id">>(
  executions: readonly T[],
  nodeId: string,
): T | null {
  let latest: T | null = null;
  for (const item of executions) {
    if (item.node_id !== nodeId) continue;
    if (!latest || item.seq >= latest.seq) latest = item;
  }
  return latest;
}

export function dryRunSummary(nodeType: string, output: unknown): DryRunSummary | null {
  if (output == null || typeof output !== "object" || Array.isArray(output)) return null;
  const record = output as Record<string, unknown>;
  if (record.dry_run !== true) return null;
  if (nodeType === "write.entity") {
    const inserted = count(record.inserted);
    const updated = count(record.updated);
    const unchanged = count(record.unchanged);
    const deleted = count(record.deleted);
    const unmatched = count(record.unmatched);
    if (
      inserted == null ||
      updated == null ||
      unchanged == null ||
      deleted == null ||
      unmatched == null
    ) {
      return null;
    }
    return { kind: "write.entity", inserted, updated, unchanged, deleted, unmatched };
  }
  if (nodeType === "state.variable" && typeof record.applied === "boolean") {
    return { kind: "state.variable", applied: record.applied };
  }
  return null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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
