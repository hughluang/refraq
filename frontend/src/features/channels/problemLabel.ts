import type { GraphProblem } from "@/features/channels/types";

export function formatGraphProblem(
  t: (key: string) => string,
  problem: GraphProblem,
): string {
  const key = `problems.${problem.code}`;
  const translated = t(key);
  const text = translated === key ? problem.detail : translated;
  const where = problem.node_id ?? problem.edge_id;
  return where ? `${text} (${where})` : text;
}
