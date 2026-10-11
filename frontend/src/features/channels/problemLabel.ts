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
