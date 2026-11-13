import type { GraphNode, NodeTypeSpec } from "./types";
import type { FlowNodeData } from "./graphValidation";
import { layoutNodePorts, CARD_WIDTH, CARD_HEIGHT } from "./portLayout";
import type { LayoutNode } from "./graphLayout";

/** Equal legacy coordinates have no recoverable runtime order; use stable ids when converting. */
export function materializeExecutionOrder(nodes: readonly GraphNode[]): GraphNode[] {
  const legacy = nodes.filter((node) => node.execution_order === undefined).sort((a, b) =>
    a.position.y - b.position.y || a.position.x - b.position.x || a.id.localeCompare(b.id));
  const start = nodes.reduce((max, node) => Math.max(max, node.execution_order ?? -1), -1) + 1;
  if (legacy.length > 0 && (!Number.isSafeInteger(start) || legacy.length - 1 > Number.MAX_SAFE_INTEGER - start)) {
    throw new RangeError("Execution priority has no safe integer capacity");
  }
  const orders = new Map(legacy.map((node, index) => [node.id, start + index]));
  return nodes.map((node) => node.execution_order === undefined ? { ...node, execution_order: orders.get(node.id)! } : node);
}

export function canvasLayoutNode(
  node: { id: string; parentId?: string; position: { x: number; y: number }; data: FlowNodeData; measured?: { width?: number; height?: number } },
  spec: NodeTypeSpec | undefined,
  errorWired: boolean,
  headerHeight?: number,
): LayoutNode {
  const frame = node.data.container != null;
  const width = frame ? undefined : node.measured?.width ?? CARD_WIDTH;
  const height = frame ? undefined : node.measured?.height ?? CARD_HEIGHT;
  const ports = layoutNodePorts(
    spec?.inputs ?? (node.data.trigger ? [] : [{ port: "main" }]),
    (spec?.outputs ?? [{ port: "main" }]).filter((port) => port.port !== "error" || node.data.onError === "error_output" || errorWired),
    { frame },
  );
  const portGeometry = (port: { port: string; top: string }) => ({
    port: port.port,
    ...(!frame ? { offset: { x: 0, y: parseFloat(port.top) / 100 * height! } } : {}),
  });
  return {
    id: node.id, parent: node.parentId, position: node.position, container: node.data.container,
    width, height, headerHeight,
    inputs: ports.inputs.map(portGeometry),
    outputs: ports.outputs.map((port) => ({ ...portGeometry(port), ...(!frame ? { offset: { x: width!, y: parseFloat(port.top) / 100 * height! } } : {}) })),
  };
}
