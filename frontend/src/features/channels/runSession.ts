import { soleStatus } from "@/features/channels/datasetView";
import { ancestorIds as frameAncestorIds } from "@/features/channels/frameLink";
import { isContainerNode } from "@/features/channels/portLayout";
import type { Graph, GraphEdge, NodeSampleScopeInput } from "@/features/channels/types";
import type { ChannelRunDetail, NodeSummary } from "@/features/channels/types";

type ChainNode = { id: string; type: string; parent?: string | null };

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

export function phaseByNode(
  detail: ChannelRunDetail,
  graph: Graph,
  latestStatus: ReadonlyMap<string, string> = new Map(),
): Map<string, NodeRunPhase> {
  const scope = executionScope(graph, detail.run.stop_at_node_id ?? null);
  const terminal = isTerminalRun(detail.run.status);
  const summaries = new Map(detail.node_summaries.map((item) => [item.node_id, item]));
  const phases = new Map<string, NodeRunPhase>();
  for (const id of scope) {
    const phase = phaseOf(summaries.get(id), latestStatus.get(id));
    if (phase) phases.set(id, phase);
    else if (terminal) phases.set(id, "dead");
    else phases.set(id, "waiting");
  }
  return phases;
}

function phaseOf(summary: NodeSummary | undefined, latest: string | undefined): NodeRunPhase | null {
  if (!summary || summary.execution_count <= 0) return null;
  const status = latest ?? soleStatus(summary.status_counts);
  if (status === "running") return "running";
  if (status === "failed") return "failed";
  if (status === "succeeded" || status === "skipped") return "succeeded";
  return "waiting";
}

export function executionCountByNode(summaries: readonly NodeSummary[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of summaries) counts.set(item.node_id, item.execution_count);
  return counts;
}

/** Changes whenever the run's status or a node's execution counts change. */
export function recordedKey(detail: ChannelRunDetail): string {
  const summaries = [...detail.node_summaries].sort((left, right) =>
    left.node_id.localeCompare(right.node_id),
  );
  return [
    detail.run.job_id,
    detail.run.status,
    ...summaries.map((item) => `${item.node_id}:${item.execution_count}:${countKey(item.status_counts)}`),
  ].join("|");
}

function countKey(counts: NodeSummary["status_counts"]): string {
  return (["running", "succeeded", "failed", "skipped"] as const)
    .map((name) => `${name}:${counts[name] ?? 0}`)
    .join(",");
}

/** Outer-to-inner For and Batch Read frames that contain `nodeId`. The node itself is not included. */
export function containerChain(nodes: readonly ChainNode[], nodeId: string): string[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const chain: string[] = [];
  let parentId = byId.get(nodeId)?.parent;
  while (parentId) {
    const parent = byId.get(parentId);
    if (!parent) break;
    if (isContainerNode(parent.type)) chain.push(parent.id);
    parentId = parent.parent;
  }
  return chain.reverse();
}

/** Round controls for a node: each container it sits in, plus itself when it is a container. */
export function roundControlIds(nodes: readonly ChainNode[], nodeId: string): string[] {
  const chain = containerChain(nodes, nodeId);
  const self = nodes.find((node) => node.id === nodeId);
  if (self && isContainerNode(self.type)) return [...chain, self.id];
  return chain;
}

/**
 * Scope sent to Node Sample. Omitted until the user pins a round, so the server
 * fills the default chain. A pin sends the whole outer-to-inner chain.
 */
export function scopeRequest(
  nodes: readonly ChainNode[],
  nodeId: string,
  pinned: Readonly<Record<string, number>>,
  resolved: readonly { container_node_id: string; round: number }[],
): NodeSampleScopeInput[] | undefined {
  const chain = containerChain(nodes, nodeId);
  if (chain.length === 0) return undefined;
  if (!chain.some((id) => pinned[id] != null)) return undefined;
  return chain.map((id) => ({
    container_node_id: id,
    round: pinned[id] ?? resolved.find((level) => level.container_node_id === id)?.round ?? 0,
  }));
}
