import type { Graph, GraphEdge } from "@/features/channels/types";
import type { ChannelRunDetail, NodeExecution } from "@/features/channels/types";

export type NodeRunPhase = "waiting" | "running" | "succeeded" | "failed";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function isTerminalRun(status: string): boolean {
  return TERMINAL.has(status);
}

export function objectKeys(value: unknown): string[] {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.keys(value).filter((key) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(key));
}

export function ancestorIds(nodeId: string, edges: readonly GraphEdge[]): Set<string> {
  const incoming = new Map<string, string[]>();
  for (const edge of edges) {
    const list = incoming.get(edge.target.node_id) ?? [];
    list.push(edge.source.node_id);
    incoming.set(edge.target.node_id, list);
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

export function executionScope(graph: Graph, stopAt: string | null): Set<string> {
  if (stopAt) {
    const closure = ancestorIds(stopAt, graph.edges);
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
  const byId = new Map(detail.node_executions.map((item) => [item.node_id, item]));
  const phases = new Map<string, NodeRunPhase>();
  for (const id of scope) {
    const execution = byId.get(id);
    if (!execution) {
      if (!terminal) phases.set(id, "waiting");
      continue;
    }
    if (execution.status === "running") phases.set(id, "running");
    else if (execution.status === "failed") phases.set(id, "failed");
    else if (execution.status === "succeeded" || execution.status === "skipped") {
      phases.set(id, "succeeded");
    }
  }
  return phases;
}

export function sampleKeysByNode(executions: readonly NodeExecution[]): Map<string, string[]> {
  const keys = new Map<string, string[]>();
  for (const item of executions) {
    const found = objectKeys(item.output_preview);
    if (found.length > 0) keys.set(item.node_id, found);
  }
  return keys;
}
