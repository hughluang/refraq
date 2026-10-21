import { ancestorIds as frameAncestorIds } from "@/features/channels/frameLink";
import type { Graph, GraphEdge } from "@/features/channels/types";
import type { ChannelRunDetail, NodeExecution } from "@/features/channels/types";

export type NodeRunPhase = "waiting" | "running" | "succeeded" | "failed" | "dead";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function isTerminalRun(status: string): boolean {
  return TERMINAL.has(status);
}

export function ancestorIds(
  nodeId: string,
  edges: readonly GraphEdge[],
  nodes: readonly { id: string; parent?: string | null }[],
): Set<string> {
  return frameAncestorIds(
    nodeId,
    edges.map((edge) => ({ source: edge.source.node_id, target: edge.target.node_id })),
    nodes.map((node) => ({ id: node.id, parentId: node.parent })),
  );
}

export function executionScope(graph: Graph, stopAt: string | null): Set<string> {
  if (stopAt) {
    const closure = ancestorIds(stopAt, graph.edges, graph.nodes);
    closure.add(stopAt);
    return closure;
  }
  const outgoing = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const list = outgoing.get(edge.source.node_id) ?? [];
    list.push(edge.target.node_id);
    outgoing.set(edge.source.node_id, list);
  }
  const seen = new Set<string>();
  const stack = graph.nodes.filter((node) => node.type.startsWith("trigger.")).map((node) => node.id);
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    stack.push(...(outgoing.get(current) ?? []));
  }
  return seen;
}

export function phaseByNode(detail: ChannelRunDetail, graph: Graph): Map<string, NodeRunPhase> {
  const scope = executionScope(graph, detail.run.stop_at_node_id ?? null);
  const terminal = isTerminalRun(detail.run.status);
  const grouped = new Map<string, NodeExecution[]>();
  for (const item of detail.node_executions) {
    const list = grouped.get(item.node_id) ?? [];
    list.push(item);
    grouped.set(item.node_id, list);
  }
  const phases = new Map<string, NodeRunPhase>();
  for (const id of scope) {
    const phase = phaseOf(grouped.get(id) ?? []);
    if (phase) phases.set(id, phase);
    else if (terminal) phases.set(id, "dead");
    else phases.set(id, "waiting");
  }
  return phases;
}

function phaseOf(items: readonly NodeExecution[]): NodeRunPhase | null {
  if (items.length === 0) return null;
  if (items.some((item) => item.status === "running")) return "running";
  const latest = items.reduce((best, item) => (item.seq > best.seq ? item : best));
  if (latest.status === "failed") return "failed";
  if (latest.status === "succeeded" || latest.status === "skipped") return "succeeded";
  return "waiting";
}

export function executionCountByNode(
  executions: readonly Pick<NodeExecution, "node_id">[],
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of executions) {
    counts.set(item.node_id, (counts.get(item.node_id) ?? 0) + 1);
  }
  return counts;
}

/** Changes whenever the run's status or any node execution's status changes. */
export function recordedKey(detail: ChannelRunDetail): string {
  return [
    detail.run.job_id,
    detail.run.status,
    ...detail.node_executions.map((item) => `${item.seq}:${item.status}`),
  ].join("|");
}

export function samplesByNode(executions: readonly NodeExecution[]): Map<string, unknown> {
  const samples = new Map<string, unknown>();
  const ordered = [...executions].sort((left, right) => left.seq - right.seq);
  for (const item of ordered) {
    if (item.output_preview == null) continue;
    samples.set(item.node_id, item.output_preview);
  }
  return samples;
}
