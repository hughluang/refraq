import { nodeTypeLabel, nodeTypeSummary } from "@/features/channels/nodeTypeCopy";

type Translate = (key: string, options?: { defaultValue?: string }) => string;

export type FilterableNodeType = {
  type: string;
  label: string;
  summary: string;
};

/** Keeps catalog order. Blank queries keep every spec. Matching uses the translated name and summary. */
export function filterNodeTypes<T extends FilterableNodeType>(
  specs: readonly T[],
  query: string,
  t: Translate,
): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...specs];
  return specs.filter((spec) => {
    const label = nodeTypeLabel(t, spec).toLowerCase();
    const summary = nodeTypeSummary(t, spec).toLowerCase();
    return label.includes(needle) || summary.includes(needle);
  });
}

export const PICKER_WIDTH = 320;
export const PICKER_MAX_HEIGHT = 420;

const PICKER_GAP = 8;

/** Stage-local origin for a 320×420 picker, clamped so the box stays inside the stage. */
export function pickerOrigin(
  anchor: { x: number; y: number },
  frame: { width: number; height: number },
  preferAbove: boolean,
): { left: number; top: number } {
  const maxLeft = Math.max(PICKER_GAP, frame.width - PICKER_WIDTH - PICKER_GAP);
  const maxTop = Math.max(PICKER_GAP, frame.height - PICKER_MAX_HEIGHT - PICKER_GAP);
  const top = preferAbove ? anchor.y - PICKER_MAX_HEIGHT - PICKER_GAP : anchor.y;
  return {
    left: Math.min(Math.max(anchor.x, PICKER_GAP), maxLeft),
    top: Math.min(Math.max(top, PICKER_GAP), maxTop),
  };
}
