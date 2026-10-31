import type { GraphProblem } from "@/features/channels/types";
import { repeatsContractSentence } from "@/lib/problem";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export type ProblemGraph = {
  nodes: readonly { id: string; name: string; type?: string }[];
  edges: readonly {
    id: string;
    source: { node_id: string };
    target: { node_id: string };
  }[];
  /** Catalog `config_schema` keyed by node type. */
  configSchemas?: Readonly<Record<string, unknown>>;
};

export function problemIdentity(problem: GraphProblem): string {
  const path = problem.path.join(".");
  return [problem.code, problem.node_id ?? "", problem.edge_id ?? "", path, problem.detail].join("|");
}

const LOOP_BODY_CODE = "CHANNEL_LOOP_BODY_INVALID";

/** Backend `detail` strings for one problem code. Each has its own sentence. */
export const LOOP_BODY_DETAIL_KEYS: Record<string, string> = {
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
  const constraint =
    problem.code === "CHANNEL_NODE_CONFIG_INVALID" ? configConstraint(t, problem, graph) : null;
  const located =
    path.length === 0
      ? text
      : constraint
        ? `${text}: ${constraint}`
        : repeatsContractSentence(problem.code, problem.detail)
          ? `${text}: ${path.join(".")}`
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

function configConstraint(
  t: Translate,
  problem: GraphProblem,
  graph: ProblemGraph,
): string | null {
  const path = problem.path;
  const key = path[path.length - 1];
  if (typeof key !== "string") return null;
  const node = graph.nodes.find((item) => item.id === problem.node_id);
  const schema = node?.type ? graph.configSchemas?.[node.type] : undefined;
  if (schema == null) return null;
  const field = schemaAt(schema, path);
  const parent = schemaAt(schema, path.slice(0, -1));
  const name = fieldTitle(t, node?.type ?? "", key);
  const required = problem.detail.match(/^'([^']+)' is a required property$/);
  if (required && required[1] === key && requiredIncludes(parent, key)) {
    return t("channels.config.constraint.required", { name });
  }
  const minimum = problem.detail.match(
    /^(-?\d+(?:\.\d+)?) is less than the minimum of (-?\d+(?:\.\d+)?)$/,
  );
  if (minimum && sameNumber(field?.minimum, minimum[2])) {
    return t("channels.config.constraint.minimum", { name, bound: minimum[2] });
  }
  const maximum = problem.detail.match(
    /^(-?\d+(?:\.\d+)?) is greater than the maximum of (-?\d+(?:\.\d+)?)$/,
  );
  if (maximum && sameNumber(field?.maximum, maximum[2])) {
    return t("channels.config.constraint.maximum", { name, bound: maximum[2] });
  }
  const minLength = field?.minLength;
  const short =
    problem.detail === "'' should be non-empty" || /^(?:'.*') is too short$/.test(problem.detail);
  if (short && typeof minLength === "number") {
    return t("channels.config.constraint.minLength", { name, bound: String(minLength) });
  }
  return null;
}

function fieldTitle(t: Translate, nodeType: string, key: string): string {
  const specificKey = `channels.config.fields.${nodeType}.${key}`;
  const specific = t(specificKey);
  if (specific && specific !== specificKey) return specific;
  const generalKey = `channels.config.fields.${key}`;
  const general = t(generalKey);
  if (general && general !== generalKey) return general;
  return key;
}

function schemaAt(
  schema: unknown,
  path: readonly (string | number)[],
): Record<string, unknown> | null {
  let current: unknown = schema;
  for (const segment of path) {
    if (!isRecord(current)) return null;
    if (typeof segment === "number") {
      current = current.items;
      continue;
    }
    if (!isRecord(current.properties)) return null;
    current = current.properties[segment];
  }
  return isRecord(current) ? current : null;
}

function requiredIncludes(schema: Record<string, unknown> | null, key: string): boolean {
  return Array.isArray(schema?.required) && schema.required.includes(key);
}

function sameNumber(bound: unknown, text: string | undefined): boolean {
  return typeof bound === "number" && text != null && bound === Number(text);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
  const raw = message ? message : null;
  if (
    code === "CHANNEL_ITERATION_VOLUME_EXCEEDED" &&
    message &&
    message !== FOR_ITERATION_VOLUME
  ) {
    return { label: message, detail: raw };
  }
  if (code) {
    const key = `problems.${code}`;
    const translated = t(key);
    if (translated !== key) {
      const detail = raw && !repeatsContractSentence(code, raw) ? raw : null;
      return { label: translated, detail };
    }
  }
  return { label: raw ?? "", detail: null };
}
