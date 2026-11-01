import type { Graph } from "@/features/channels/types";

/** Path registered by the published version for this trigger node. Draft edits do not change it. */
export function publishedInboundPath(graph: Graph | null, nodeId: string): string | null {
  const node = graph?.nodes.find((item) => item.id === nodeId && item.type === "trigger.inbound");
  const path = node?.config.path;
  return typeof path === "string" && path.length > 0 ? path : null;
}
