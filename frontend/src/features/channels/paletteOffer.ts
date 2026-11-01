export type PaletteNode = {
  type: string;
  trigger?: boolean;
  config: Record<string, unknown>;
};

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

/** Respond belongs in the palette only while the graph trigger is inbound in respond_node mode. */
export function respondNodeOffered(nodes: readonly PaletteNode[]): boolean {
  const trigger = nodes.find((node) => node.trigger === true || node.type.startsWith("trigger."));
  if (trigger == null || trigger.type !== "trigger.inbound") return false;
  return record(trigger.config.response)?.mode === "respond_node";
}
