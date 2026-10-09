import type { NodeTypeSpec } from "@/features/channels/types";

type Translate = (key: string, options?: { defaultValue?: string }) => string;

export function nodeTypeLabel(t: Translate, spec: Pick<NodeTypeSpec, "type" | "label">): string {
  return t(`channelNodeTypes.${spec.type}.label`, { defaultValue: spec.label });
}

export function nodeTypeSummary(
  t: Translate,
  spec: Pick<NodeTypeSpec, "type" | "summary">,
): string {
  return t(`channelNodeTypes.${spec.type}.summary`, { defaultValue: spec.summary });
}
