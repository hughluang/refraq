import type { ChannelRun } from "@/features/channels/types";

type RunSubject = Pick<ChannelRun, "target" | "version">;

/** What a Channel Run executed: a draft, or a resolved published version. */
export function formatRunSubject(
  run: RunSubject,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (run.target === "draft") {
    return t("channels.runs.subject.draft");
  }
  if (run.version == null) {
    return "";
  }
  return t("channels.runs.subject.version", { number: run.version });
}

/** Node label when the graph has a name or ref. Otherwise the id. */
export function nodeDisplayName(
  nodes: readonly { id: string; name: string; ref?: string }[],
  nodeId: string | null | undefined,
): string | null {
  if (!nodeId) return null;
  const node = nodes.find((item) => item.id === nodeId);
  const name = node?.name.trim() ?? "";
  if (name) return name;
  const ref = node?.ref?.trim() ?? "";
  return ref || nodeId;
}

/** Graph name of a failed node, or its id when the graph has no name. */
export function formatFailedNode(
  nodes: readonly { id: string; name: string }[],
  failedNodeId: string | null,
): string | null {
  if (!failedNodeId) return null;
  const name = nodes.find((node) => node.id === failedNodeId)?.name.trim() ?? "";
  return name || failedNodeId;
}
