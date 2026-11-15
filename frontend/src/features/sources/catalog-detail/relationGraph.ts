import type { CatalogJoin, CatalogObject, JoinPath } from "@/features/sources/types";
import { objectRefFromColumnLocator } from "./joinEdges";

export type RelationColumn = { id: string; name: string; presence: "present" | "absent" | "unknown"; dataType?: string };
export type RelationObject = { id: string; name: string; identity: string; focused: boolean; columns: RelationColumn[] };
export type RelationEdge = { id: string; source: string; target: string; sourceHandle: string; targetHandle: string; kind: string; rejected: boolean; lane: number };

export function relationCurve(sourceX: number, sourceY: number, targetX: number, targetY: number, lane: number, self: boolean) {
  const spread = 72 + lane * 24;
  if (self) return { path: `M ${sourceX},${sourceY} C ${sourceX - spread},${sourceY} ${targetX - spread},${targetY} ${targetX},${targetY}`, x: sourceX - spread * 0.75, y: (sourceY + targetY) / 2 };
  const direction = sourceX < targetX ? 1 : -1;
  const bend = direction * (lane - 1) * 32;
  const reach = Math.max(64, Math.abs(targetX - sourceX) * 0.4);
  return { path: `M ${sourceX},${sourceY} C ${sourceX + direction * reach},${sourceY + bend} ${targetX - direction * reach},${targetY + bend} ${targetX},${targetY}`, x: (sourceX + targetX) / 2, y: (sourceY + targetY) / 2 + bend * 0.75 };
}

type GraphRelation = Pick<CatalogJoin, "id" | "from_column_id" | "to_column_id" | "from_column_locator_key" | "to_column_locator_key" | "join_kind" | "is_rejected">;

export function projectRoute(object: CatalogObject, route: JoinPath, joins: readonly CatalogJoin[]) {
  const definitions = route.hops.map((hop) => joins.find((join) => join.id === hop.join_id));
  const graph = projectRelations(object, route.hops.map((hop, index) => ({ ...(definitions[index] ?? hop), id: `hop:${index}` })));
  return { nodes: graph.nodes, edges: graph.edges.map((edge, index) => ({ ...edge, stored: Boolean(definitions[index]) })) };
}

export function projectRelations(object: CatalogObject, joins: readonly GraphRelation[]) {
  const nodes: RelationObject[] = [{ id: object.locator_key, name: `${object.schema_name}.${object.name}`, identity: object.locator_key, focused: true, columns: [] }];
  function endpoint(id: string, locator?: string | null) {
    const local = object.columns.find((column) => column.id === id);
    const ref = local ? object.locator_key : objectRefFromColumnLocator(locator);
    const key = ref ?? `unresolved:${id}`;
    let node = nodes.find((item) => item.id === key);
    if (!node) {
      const parts = ref?.split("/");
      node = { id: key, name: parts ? `${parts[3]}.${parts[5]}` : id, identity: ref ?? locator ?? id, focused: false, columns: [] };
      nodes.push(node);
    }
    if (!node.columns.some((column) => column.id === id)) {
      node.columns.push({ id, name: local?.name ?? (ref ? locator!.split("/")[7] : id), presence: local ? (local.is_present ? "present" : "absent") : "unknown", dataType: local?.data_type });
    }
    return key;
  }
  const lanes = new Map<string, number>();
  const edges: RelationEdge[] = joins.map((join) => {
    const source = endpoint(join.from_column_id, join.from_column_locator_key);
    const target = endpoint(join.to_column_id, join.to_column_locator_key);
    const pair = [source, target].sort().join(":");
    const lane = (lanes.get(pair) ?? 0) + 1;
    lanes.set(pair, lane);
    return {
      id: join.id, source, target,
      sourceHandle: `from:${join.from_column_id}:${source === target || source !== object.locator_key ? "left" : "right"}`,
      targetHandle: `to:${join.to_column_id}:${source !== target && target === object.locator_key ? "right" : "left"}`,
      kind: join.join_kind ?? "INNER", rejected: Boolean(join.is_rejected), lane,
    };
  });
  nodes.forEach((node) => node.columns.sort((a, b) => a.id.localeCompare(b.id)));
  return { nodes, edges };
}
