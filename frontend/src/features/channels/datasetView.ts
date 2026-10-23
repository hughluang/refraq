import type { Graph, NodeExecution, NodeSummary } from "@/features/channels/types";

export type DatasetColumn = { name: string; type: string };

export type DatasetReference = {
  dataset_id: string;
  columns: DatasetColumn[];
  count: number;
};

export const DATASET_ROW_PAGE = 200;

export function isDatasetReference(value: unknown): value is DatasetReference {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (typeof record.dataset_id !== "string" || record.dataset_id === "") return false;
  if (typeof record.count !== "number" || !Number.isInteger(record.count) || record.count < 0) {
    return false;
  }
  if (!Array.isArray(record.columns)) return false;
  return record.columns.every((column) => {
    if (typeof column !== "object" || column === null || Array.isArray(column)) return false;
    const item = column as Record<string, unknown>;
    return typeof item.name === "string" && typeof item.type === "string";
  });
}

/** Dataset references nested anywhere in an execution preview. */
export function datasetReferencesIn(value: unknown): DatasetReference[] {
  const found: DatasetReference[] = [];
  const seen = new Set<unknown>();
  const visit = (current: unknown) => {
    if (typeof current !== "object" || current === null) return;
    if (seen.has(current)) return;
    seen.add(current);
    if (isDatasetReference(current)) {
      found.push({
        dataset_id: current.dataset_id,
        count: current.count,
        columns: current.columns.map((column) => ({ name: column.name, type: column.type })),
      });
      return;
    }
    const entries = Array.isArray(current) ? current : Object.values(current);
    for (const item of entries) visit(item);
  };
  visit(value);
  return found;
}

/**
 * `_ord` window for one Batch Read round: `(index * batchSize, (index + 1) * batchSize]`,
 * cut by `total` when the dataset is shorter than the nominal end.
 */
export function batchOrdWindow(
  index: number,
  batchSize: number,
  total: number,
): { afterOrd: number; endOrd: number } {
  const afterOrd = index * batchSize;
  const endOrd = Math.min((index + 1) * batchSize, total);
  return { afterOrd, endOrd: Math.max(afterOrd, endOrd) };
}

/** Page size for the next row request inside a window. Null when the window is exhausted. */
export function datasetRowLimit(afterOrd: number, endOrd: number): number | null {
  const room = endOrd - afterOrd;
  if (room <= 0) return null;
  return Math.min(DATASET_ROW_PAGE, room);
}

export function rowsInsideWindow<T extends { _ord: number }>(
  items: readonly T[],
  endOrd: number,
): T[] {
  return items.filter((item) => item._ord <= endOrd);
}

export function latestExecutionQuery(
  summary: NodeSummary,
): { node_id: string; limit: 1; offset: number } | null {
  if (summary.execution_count <= 0) return null;
  return {
    node_id: summary.node_id,
    limit: 1,
    offset: summary.execution_count - 1,
  };
}

export function soleStatus(counts: NodeSummary["status_counts"]): string | null {
  let only: string | null = null;
  for (const [name, count] of Object.entries(counts)) {
    if (typeof count !== "number" || count <= 0) continue;
    if (only != null) return null;
    only = name;
  }
  return only;
}

/** A direct child execution of a Batch Read, addressed by its round index. */
export function batchReadRound(
  graph: Graph,
  execution: Pick<NodeExecution, "node_id" | "round" | "container_seq">,
): { parentId: string; index: number; containerSeq: number } | null {
  if (execution.round == null || execution.container_seq == null) return null;
  const node = graph.nodes.find((item) => item.id === execution.node_id);
  const parentId = node?.parent;
  if (!parentId) return null;
  const parent = graph.nodes.find((item) => item.id === parentId);
  if (!parent || parent.type !== "volume.batch_read") return null;
  return { parentId, index: execution.round, containerSeq: execution.container_seq };
}

export function readBatchOutput(value: unknown): { batchSize: number; total: number } | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const batchSize = record.batch_size;
  const total = record.total;
  if (typeof batchSize !== "number" || !Number.isInteger(batchSize) || batchSize < 1) return null;
  if (typeof total !== "number" || !Number.isInteger(total) || total < 0) return null;
  return { batchSize, total };
}
