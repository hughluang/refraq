import type { GraphProblem } from "@/features/channels/types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export type ProblemGraph = {
  nodes: readonly { id: string; name: string }[];
  edges: readonly {
    id: string;
    source: { node_id: string };
    target: { node_id: string };
  }[];
};

export function problemIdentity(problem: GraphProblem): string {
  const path = problem.path.join(".");
  return [problem.code, problem.node_id ?? "", problem.edge_id ?? "", path, problem.detail].join("|");
}

export function formatGraphProblem(
  t: Translate,
  problem: GraphProblem,
  graph: ProblemGraph,
  options?: { nodeName?: boolean },
): string {
  const key = `problems.${problem.code}`;
  const translated = t(key);
  const text = translated === key ? problem.detail : translated;
  const path = problem.path;
  const located =
    path.length === 0
      ? text
      : translated === key
        ? `${path.join(".")}: ${text}`
        : `${text}: ${path.join(".")} — ${problem.detail}`;
  const place = problemPlace(t, problem, graph, options?.nodeName !== false);
  return place ? `${located} (${place})` : located;
}

function problemPlace(
  t: Translate,
  problem: GraphProblem,
  graph: ProblemGraph,
  includeNodeName: boolean,
): string | null {
  if (problem.edge_id) {
    const edge = graph.edges.find((item) => item.id === problem.edge_id);
    if (!edge) return null;
    const source = lookupName(graph, edge.source.node_id);
    const target = lookupName(graph, edge.target.node_id);
    if (source && target) return t("channels.canvas.problemEdge", { source, target });
    return source ?? target;
  }
  if (!includeNodeName || !problem.node_id) return null;
  return lookupName(graph, problem.node_id);
}

function lookupName(graph: ProblemGraph, nodeId: string): string | null {
  const name = graph.nodes.find((node) => node.id === nodeId)?.name.trim();
  return name ? name : null;
}

export function fieldConstraint(
  problems: readonly GraphProblem[],
  fieldKey: string,
): string | undefined {
  const lines: string[] = [];
  for (const problem of problems) {
    const path = problem.path;
    if (path[0] !== fieldKey) continue;
    const rest = path.slice(1).map(String).join(".");
    if (rest) lines.push(`${rest} — ${problem.detail}`);
    else lines.push(problem.detail);
  }
  return lines.length > 0 ? lines.join("; ") : undefined;
}

export function problemColor(severity: "error" | "warning" | undefined): "red" | "yellow" {
  return severity === "warning" ? "yellow" : "red";
}

export function formatRunError(
  t: (key: string) => string,
  code: string | null,
  message: string | null,
): { label: string; detail: string | null } {
  const detail = message ? message : null;
  if (code) {
    const key = `problems.${code}`;
    const translated = t(key);
    if (translated !== key) return { label: translated, detail };
  }
  return { label: detail ?? "", detail: null };
}
