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

const LOOP_BODY_CODE = "CHANNEL_LOOP_BODY_INVALID";

/** Backend `detail` strings for one problem code. Each has its own sentence. */
const LOOP_BODY_DETAIL_KEYS: Record<string, string> = {
  "parent does not name a container": "problems.CHANNEL_LOOP_BODY_INVALID.parent",
  "parent chain contains a cycle": "problems.CHANNEL_LOOP_BODY_INVALID.cycle",
  "Edge crosses a container frame": "problems.CHANNEL_LOOP_BODY_INVALID.cross",
  "A container frame is entered only from each": "problems.CHANNEL_LOOP_BODY_INVALID.entry",
  "each connects only to a direct child of this container": "problems.CHANNEL_LOOP_BODY_INVALID.each",
};

export function formatGraphProblem(
  t: Translate,
  problem: GraphProblem,
  graph: ProblemGraph,
  options?: { nodeName?: boolean },
): string {
  const key = `problems.${problem.code}`;
  const text = problemSentence(t, problem, key);
  const path = problem.path;
  const located =
    path.length === 0
      ? text
      : text === problem.detail
        ? `${path.join(".")}: ${text}`
        : `${text}: ${path.join(".")} — ${problem.detail}`;
  const place = problemPlace(t, problem, graph, options?.nodeName !== false);
  return place ? `${located} (${place})` : located;
}

function problemSentence(t: Translate, problem: GraphProblem, codeKey: string): string {
  if (problem.code === LOOP_BODY_CODE) {
    const detailKey = LOOP_BODY_DETAIL_KEYS[problem.detail];
    if (detailKey) {
      const specific = t(detailKey);
      if (specific !== detailKey) return specific;
    }
  }
  const translated = t(codeKey);
  return translated === codeKey ? problem.detail : translated;
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

export type FieldMessage = {
  text: string;
  severity: "error" | "warning";
};

export function fieldMessages(
  t: Translate,
  problems: readonly GraphProblem[],
  fieldKey: string,
  graph: ProblemGraph,
): FieldMessage[] {
  return problems
    .filter((problem) => problem.path[0] === fieldKey)
    .map((problem) => ({
      text: formatGraphProblem(t, problem, graph, { nodeName: false }),
      severity: problem.severity === "warning" ? "warning" : "error",
    }));
}


const FOR_ITERATION_VOLUME =
  "For iteration output exceeds 16 MiB. Read the items in batches.";

export function formatRunError(
  t: (key: string) => string,
  code: string | null,
  message: string | null,
): { label: string; detail: string | null } {
  const detail = message ? message : null;
  if (
    code === "CHANNEL_ITERATION_VOLUME_EXCEEDED" &&
    message &&
    message !== FOR_ITERATION_VOLUME
  ) {
    return { label: message, detail };
  }
  if (code) {
    const key = `problems.${code}`;
    const translated = t(key);
    if (translated !== key) return { label: translated, detail };
  }
  return { label: detail ?? "", detail: null };
}
