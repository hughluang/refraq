"use client";

import { Button, Group, Text, useComputedColorScheme } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { BaseEdge, Background, EdgeLabelRenderer, Handle, MarkerType, Position, ReactFlow, type Edge, type EdgeProps, type Node, type NodeProps, useUpdateNodeInternals, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { CatalogJoin, CatalogObject, JoinPath } from "@/features/sources/types";
import { projectRelations, projectRoute, relationCurve, type RelationObject } from "./relationGraph";
import { relationName } from "./RelationSummary";
import styles from "./RelationGraph.module.css";

type RelationFlowEdge = Edge<{ lane: number }, "relation"> & { data: { lane: number } };
type ObjectNode = Node<RelationObject & { selectColumn?: (id: string) => void; column: string | null; endpoints: string[] }, "object">;
function ObjectCard({ id, data }: NodeProps<ObjectNode>) {
  const t = useTranslate();
  const updateInternals = useUpdateNodeInternals();
  const columnKey = data.columns.map((column) => column.id).join(":");
  useEffect(() => { updateInternals(id); }, [id, columnKey, updateInternals]);
  return <div className={styles.card} data-focused={data.focused || undefined}>
    <div className={styles.heading}>
      <Text size="sm" fw={600}>{data.name}</Text>
      <Text size="xs" c="dimmed" className={styles.identity}>{data.identity}</Text>
      {data.focused ? <Text size="xs" c="dimmed">{t("catalog.joins.graph.current")}</Text> : null}
    </div>
    {data.columns.map((column) => <div key={column.id} className={styles.column} data-highlight={data.column === column.id || data.endpoints.includes(column.id) || undefined}>
      {([Position.Left, Position.Right] as const).flatMap((side) => (["source", "target"] as const).map((type) => <Handle key={`${side}:${type}`} type={type} position={side} id={`${type === "source" ? "from" : "to"}:${column.id}:${side}`} isConnectable={false} />))}
      {data.selectColumn ? <button type="button" className={`nodrag nopan ${styles.columnButton}`} aria-pressed={data.column === column.id} onClick={() => data.selectColumn?.(column.id)}>
        <span>{column.name}</span><span className={styles.columnMeta}>{column.dataType ?? t("catalog.joins.graph.unknown")}{column.presence === "absent" ? ` · ${t("catalog.fields.absentValue")}` : ""}</span>
      </button> : <div className={styles.columnButton}>
        <span>{column.name}</span><span className={styles.columnMeta}>{column.dataType ?? t("catalog.joins.graph.unknown")}{column.presence === "absent" ? ` · ${t("catalog.fields.absentValue")}` : ""}</span>
      </div>}
    </div>)}
  </div>;
}
function RelationLine(props: EdgeProps<RelationFlowEdge>) {
  const { path, x, y } = relationCurve(props.sourceX, props.sourceY, props.targetX, props.targetY, props.data.lane, props.source === props.target);
  return <><BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={props.style} interactionWidth={24} /><EdgeLabelRenderer><span className={`nodrag nopan ${styles.edgeLabel}`} data-selected={props.selected || undefined} style={{ opacity: props.style?.opacity, transform: `translate(-50%, -50%) translate(${x}px,${y}px)` }}>{props.label}</span></EdgeLabelRenderer></>;
}
const nodeTypes = { object: ObjectCard };
const edgeTypes = { relation: RelationLine };

export function RelationGraph({ object, joins, selected, onSelect, column, onColumn, route }: { object: CatalogObject; joins: CatalogJoin[]; selected: string | null; onSelect: (join: CatalogJoin, returnTarget: SVGElement) => void; column: string | null; onColumn: (id: string | null) => void; route?: JoinPath }) {
  const t = useTranslate();
  const colorMode = useComputedColorScheme("light");
  const flow = useRef<ReactFlowInstance<ObjectNode, RelationFlowEdge> | null>(null);
  const graph = useMemo(() => route ? projectRoute(object, route, joins) : projectRelations(object, joins), [object, joins, route]);
  const selectedJoin = joins.find((join) => join.id === selected);
  const heights = useRef(new Map<string, number>());
  const [, resize] = useState(0);
  let nextY = 80;
  const nodes: ObjectNode[] = graph.nodes.map((node, index) => {
    const position = { x: index === 0 ? 160 : 720, y: index === 0 ? 180 : nextY };
    if (index > 0) nextY += (heights.current.get(node.id) ?? 180 + node.columns.length * 64) + 120;
    return { id: node.id, type: "object", position, data: { ...node, column, endpoints: selectedJoin ? [selectedJoin.from_column_id, selectedJoin.to_column_id] : [], selectColumn: route ? undefined : (id) => onColumn(column === id ? null : id) }, draggable: false, selectable: false };
  });
  const edges: RelationFlowEdge[] = graph.edges.map((edge, index) => {
    const join = joins.find((item) => item.id === edge.id);
    const stored = !route || ("stored" in edge && edge.stored);
    const label = route ? `${index + 1} · ${t(stored ? "catalog.joins.path.stored" : "catalog.joins.path.traversal")} · ${edge.kind}` : `${edge.kind}${edge.rejected ? ` · ${t("catalog.joins.state.rejected")}` : ""}`;
    return { ...edge, type: "relation", data: { lane: edge.lane }, selected: Boolean(route) || edge.id === selected, label, ariaLabel: route ? label : `${relationName(object, join!)} · ${edge.kind}`, markerEnd: { type: MarkerType.ArrowClosed, color: "var(--mantine-color-dimmed)" }, style: { stroke: route || edge.id === selected ? "var(--mantine-primary-color-filled)" : "var(--mantine-color-dimmed)", strokeWidth: route || edge.id === selected ? 3 : 1.5, strokeDasharray: !stored || edge.rejected ? "6 4" : undefined, opacity: column && join && join.from_column_id !== column && join.to_column_id !== column ? 0.15 : 1 }, focusable: !route };
  });

  return <section className={styles.canvas} aria-label={t("catalog.joins.graph.title")}>
    <Group gap="xs" className={styles.tools}>
      <Button size="xs" variant="default" onClick={() => void flow.current?.fitView({ padding: 0.35, duration: 0, maxZoom: 1 })}>{t("catalog.joins.graph.fit")}</Button>
      {column ? <Button size="xs" variant="default" onClick={() => onColumn(null)}>{t("catalog.joins.graph.clearColumn")}</Button> : null}
    </Group>
    <ReactFlow<ObjectNode, RelationFlowEdge> key={object.id} nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} colorMode={colorMode} onNodesChange={(changes) => { let changed = false; for (const change of changes) { if (change.type === "dimensions" && change.dimensions && heights.current.get(change.id) !== change.dimensions.height) { heights.current.set(change.id, change.dimensions.height); changed = true; } } if (changed) resize((value) => value + 1); }} onInit={(instance) => { flow.current = instance; }} fitView fitViewOptions={{ padding: 0.35, maxZoom: 1 }} defaultViewport={{ x: 12, y: 12, zoom: 0.7 }} nodesConnectable={false} nodesDraggable={false} edgesReconnectable={false} deleteKeyCode={null} minZoom={0.6} maxZoom={1.5} onEdgeClick={(event, edge) => { const target = (event.target as Element).closest<SVGElement>(".react-flow__edge"); const join = !route && joins.find((join) => join.id === edge.id); if (join && target) onSelect(join, target); }} onKeyDown={(event) => { if (event.key !== "Enter" && event.key !== " ") return; const target = (event.target as Element).closest<SVGElement>(".react-flow__edge"); const id = target?.getAttribute("data-id"); const join = !route && joins.find((item) => item.id === id); if (join && target) { event.preventDefault(); onSelect(join, target); } }} proOptions={{ hideAttribution: true }}><Background /></ReactFlow>
  </section>;
}
