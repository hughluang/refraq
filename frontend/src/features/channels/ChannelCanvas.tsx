"use client";

import { ActionIcon, Button, CloseButton, Group, Paper, Popover, Stack, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import {
  Background,
  BaseEdge,
  Controls,
  EdgeToolbar,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  getBezierPath,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

import "@xyflow/react/dist/style.css";
import "./ChannelCanvas.css";

import {
  createHistory,
  pushHistory,
  redoHistory,
  shouldCommitEdgeChanges,
  shouldCommitNodeChanges,
  undoHistory,
  type History,
} from "@/features/channels/canvasHistory";
import {
  defaultConfig,
  type SchemaObject,
} from "@/features/channels/configSchemaForm";
import {
  connectionAllowed,
  emptyNodeData,
  flowFromGraph,
  graphFromFlow,
  newGraphId,
  outputTargetTypes,
  type FlowNodeData,
} from "@/features/channels/graphValidation";
import { NodeConfigPanel } from "@/features/channels/NodeConfigPanel";
import { nodeTypeLabel, nodeTypeSummary } from "@/features/channels/nodeTypeCopy";
import { formatGraphProblem } from "@/features/channels/problemLabel";
import type { Graph, GraphProblem, NodeTypeSpec } from "@/features/channels/types";

type ChannelNode = Node<FlowNodeData, "channel">;

type CanvasSnapshot = {
  nodes: ChannelNode[];
  edges: Edge[];
};

export type CanvasFocus = {
  token: number;
  nodeId: string | null;
  edgeId: string | null;
};

type PickerState =
  | { kind: "catalog" }
  | {
      kind: "connect";
      position: { x: number; y: number };
      sourceId: string;
      sourceHandle: string;
      specs: NodeTypeSpec[];
    };

const CHANNEL_EDGE_TYPE = "channel";
const nodeTypes = { channel: ChannelFlowNode };
const edgeTypes = { [CHANNEL_EDGE_TYPE]: ChannelFlowEdge };
const PROBLEM_STROKE = "var(--mantine-color-red-6)";
const CanvasEditableContext = createContext(false);
const CanvasCatalogContext = createContext<readonly NodeTypeSpec[]>([]);

type Props = {
  graph: Graph;
  catalog: NodeTypeSpec[];
  editable: boolean;
  problems: GraphProblem[];
  problemNodeIds: ReadonlySet<string>;
  problemEdgeIds: ReadonlySet<string>;
  focus: CanvasFocus | null;
  onChange: (graph: Graph) => void;
  onFocusProblem: (problem: GraphProblem) => void;
};

export function ChannelCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <ChannelCanvasBody {...props} />
    </ReactFlowProvider>
  );
}

function ChannelCanvasBody({
  graph,
  catalog,
  editable,
  problems,
  problemNodeIds,
  problemEdgeIds,
  focus,
  onChange,
  onFocusProblem,
}: Props) {
  const t = useTranslate();
  const { screenToFlowPosition } = useReactFlow();
  const entryTypes = useMemo(
    () => new Set(catalog.filter((item) => item.entry).map((item) => item.type)),
    [catalog],
  );
  const initial = useMemo(
    () => flowFromGraph(graph, entryTypes),
    // The canvas owns edits after mount. Reload by remounting the parent key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const seededNodes = initial.nodes.map((node) => ({ ...node, type: "channel" as const }));
  const seededEdges = channelEdges(initial.edges);
  const [nodes, setNodes] = useState<ChannelNode[]>(seededNodes);
  const [edges, setEdges] = useState<Edge[]>(seededEdges);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerState | null>(null);
  const [problemsOpen, setProblemsOpen] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const historyRef = useRef<History<CanvasSnapshot>>(
    createHistory(snapshotOf(seededNodes, seededEdges)),
  );
  const commitQueued = useRef(false);
  const flowRootRef = useRef<HTMLDivElement>(null);
  const undoRef = useRef<() => void>(() => {});
  const redoRef = useRef<() => void>(() => {});
  const problemNodeIdsRef = useRef(problemNodeIds);
  const problemEdgeIdsRef = useRef(problemEdgeIds);
  nodesRef.current = nodes;
  edgesRef.current = edges;
  problemNodeIdsRef.current = problemNodeIds;
  problemEdgeIdsRef.current = problemEdgeIds;
  const settingsRef = useRef(graph.settings);
  settingsRef.current = graph.settings;

  const problemKey = `${[...problemNodeIds].sort().join(",")}|${[...problemEdgeIds].sort().join(",")}`;
  useEffect(() => {
    const painted = paintProblems(nodesRef.current, edgesRef.current);
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
    // problemKey is the stable digest of both sets. The sets themselves are new each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemKey]);

  const emit = (nextNodes: ChannelNode[], nextEdges: Edge[]) => {
    onChange(
      graphFromFlow(
        nextNodes.map((node) => ({
          id: node.id,
          position: node.position,
          data: node.data,
        })),
        nextEdges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
        })),
        settingsRef.current,
      ),
    );
  };

  const graphNow = () =>
    graphFromFlow(
      nodesRef.current.map((node) => ({
        id: node.id,
        position: node.position,
        data: node.data,
      })),
      edgesRef.current.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
      })),
      settingsRef.current,
    );

  const publishHistory = (next: History<CanvasSnapshot>) => {
    historyRef.current = next;
    setCanUndo(next.past.length > 0);
    setCanRedo(next.future.length > 0);
  };

  const pushSnap = () => {
    const snap = snapshotOf(nodesRef.current, edgesRef.current);
    if (sameSnapshot(historyRef.current.present, snap)) return;
    publishHistory(pushHistory(historyRef.current, snap));
  };

  const commitNow = () => {
    commitQueued.current = false;
    pushSnap();
  };

  const flushCommit = () => {
    if (!commitQueued.current) return;
    commitQueued.current = false;
    pushSnap();
  };

  const scheduleCommit = () => {
    if (commitQueued.current) return;
    commitQueued.current = true;
    queueMicrotask(() => {
      if (!commitQueued.current) return;
      commitQueued.current = false;
      pushSnap();
    });
  };

  const restore = (snap: CanvasSnapshot) => {
    const painted = paintProblems(snap.nodes, snap.edges);
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
    setSelectedId(painted.nodes.find((node) => node.selected)?.id ?? null);
    emit(painted.nodes, painted.edges);
  };

  const undo = () => {
    flushCommit();
    const next = undoHistory(historyRef.current);
    if (next === historyRef.current) return;
    publishHistory(next);
    restore(next.present);
  };

  const redo = () => {
    flushCommit();
    const next = redoHistory(historyRef.current);
    if (next === historyRef.current) return;
    publishHistory(next);
    restore(next.present);
  };

  undoRef.current = undo;
  redoRef.current = redo;

  useEffect(() => {
    if (!editable) return;
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.code !== "KeyZ") return;
      const target = event.target;
      if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
      }
      event.preventDefault();
      if (event.shiftKey) redoRef.current();
      else undoRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editable]);

  useEffect(() => {
    if (!focus) return;
    if (focus.nodeId) {
      const nextNodes = nodesRef.current.map((node) => ({
        ...node,
        selected: node.id === focus.nodeId,
      }));
      const nextEdges = edgesRef.current.map((edge) => ({ ...edge, selected: false }));
      nodesRef.current = nextNodes;
      edgesRef.current = nextEdges;
      setNodes(nextNodes);
      setEdges(nextEdges);
      setSelectedId(focus.nodeId);
      setPicker(null);
      return;
    }
    if (focus.edgeId) {
      const nextNodes = nodesRef.current.map((node) => ({ ...node, selected: false }));
      const nextEdges = edgesRef.current.map((edge) => ({
        ...edge,
        selected: edge.id === focus.edgeId,
      }));
      nodesRef.current = nextNodes;
      edgesRef.current = nextEdges;
      setNodes(nextNodes);
      setEdges(nextEdges);
      setSelectedId(null);
      setPicker(null);
    }
  }, [focus]);

  const placeNode = (
    spec: NodeTypeSpec,
    position: { x: number; y: number },
    link?: { sourceId: string; sourceHandle: string },
  ) => {
    if (!editable) return;
    const label = nodeTypeLabel(t, spec);
    const count = nodesRef.current.filter((node) => node.data.nodeType === spec.type).length;
    const name = count === 0 ? label : `${label} ${count + 1}`;
    const id = newGraphId("nd");
    const created: ChannelNode = {
      id,
      type: "channel",
      position,
      selected: true,
      data: emptyNodeData(
        spec.type,
        name,
        defaultConfig(spec.config_schema as SchemaObject),
        spec.entry,
      ),
    };
    const nextNodes = [...nodesRef.current.map((node) => ({ ...node, selected: false })), created];
    let nextEdges: Edge[] = edgesRef.current.map((edge) => ({ ...edge, selected: false }));
    if (link) {
      const draft = graphFromFlow(
        nextNodes.map((node) => ({
          id: node.id,
          position: node.position,
          data: node.data,
        })),
        nextEdges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
        })),
        settingsRef.current,
      );
      const input = spec.inputs.find((port) =>
        connectionAllowed(draft, catalog, {
          source: link.sourceId,
          target: id,
          sourceHandle: link.sourceHandle,
          targetHandle: port.port,
        }),
      );
      if (input) {
        nextEdges = channelEdges(
          addEdge(
            {
              source: link.sourceId,
              target: id,
              sourceHandle: link.sourceHandle,
              targetHandle: input.port,
            },
            nextEdges,
            { getEdgeId: () => newGraphId("ed") },
          ),
        );
      }
    }
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    setSelectedId(id);
    setPicker(null);
    emit(nextNodes, nextEdges);
    commitNow();
  };

  const openPosition = () => {
    const pane = flowRootRef.current?.querySelector(".react-flow");
    const rect = pane instanceof HTMLElement ? pane.getBoundingClientRect() : null;
    const center = rect
      ? screenToFlowPosition({
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        })
      : { x: 160, y: 120 };
    const stepX = 180;
    const stepY = 96;
    for (let index = 0; index < 16; index += 1) {
      const column = index % 4;
      const row = Math.floor(index / 4);
      const position = {
        x: center.x + (column - 1.5) * stepX,
        y: center.y + (row - 0.5) * stepY,
      };
      const blocked = nodesRef.current.some(
        (node) =>
          Math.abs(node.position.x - position.x) < 100 &&
          Math.abs(node.position.y - position.y) < 48,
      );
      if (!blocked) return position;
    }
    return { x: center.x + nodesRef.current.length * 24, y: center.y };
  };

  const onNodesChange = (changes: NodeChange<ChannelNode>[]) => {
    const next = applyNodeChanges(changes, nodesRef.current);
    nodesRef.current = next;
    setNodes(next);
    const selected = next.find((node) => node.selected);
    setSelectedId(selected?.id ?? null);
    if (selected) setPicker(null);
    if (selected && edgesRef.current.some((edge) => edge.selected)) {
      const cleared = edgesRef.current.map((edge) => ({ ...edge, selected: false }));
      edgesRef.current = cleared;
      setEdges(cleared);
    }
    if (shouldCommitNodeChanges(changes)) {
      emit(next, edgesRef.current);
      scheduleCommit();
    } else if (changes.some((change) => change.type === "position")) {
      emit(next, edgesRef.current);
    }
  };

  const onEdgesChange = (changes: EdgeChange[]) => {
    const next = applyEdgeChanges(changes, edgesRef.current);
    edgesRef.current = next;
    setEdges(next);
    const selected = next.find((edge) => edge.selected);
    if (selected) {
      setSelectedId(null);
      if (nodesRef.current.some((node) => node.selected)) {
        const cleared = nodesRef.current.map((node) => ({ ...node, selected: false }));
        nodesRef.current = cleared;
        setNodes(cleared);
      }
    }
    if (shouldCommitEdgeChanges(changes)) {
      emit(nodesRef.current, next);
      scheduleCommit();
    }
  };

  const onConnect = (connection: Connection) => {
    if (!editable || !connectionAllowed(graphNow(), catalog, connection)) return;
    const next = channelEdges(
      addEdge(connection, edgesRef.current, { getEdgeId: () => newGraphId("ed") }),
    );
    if (next === edgesRef.current) return;
    edgesRef.current = next;
    setEdges(next);
    emit(nodesRef.current, next);
    commitNow();
  };

  const onConnectEnd = (
    event: MouseEvent | TouchEvent,
    connectionState: {
      isValid: boolean | null;
      fromNode: { id: string } | null;
      fromHandle: { type: string; id?: string | null } | null;
    },
  ) => {
    if (!editable || connectionState.isValid === true) return;
    if (!connectionState.fromNode || connectionState.fromHandle?.type !== "source") return;
    const point = eventPoint(event);
    if (!point) return;
    const under = document.elementFromPoint(point.x, point.y);
    if (!under?.closest(".react-flow")) return;
    const sourceHandle = connectionState.fromHandle.id || "main";
    const specs = outputTargetTypes(graphNow(), catalog, connectionState.fromNode.id, sourceHandle);
    if (specs.length === 0) return;
    releaseSelection();
    setPicker({
      kind: "connect",
      position: screenToFlowPosition(point),
      sourceId: connectionState.fromNode.id,
      sourceHandle,
      specs,
    });
  };

  const releaseSelection = () => {
    if (nodesRef.current.some((node) => node.selected)) {
      const nextNodes = nodesRef.current.map((node) =>
        node.selected ? { ...node, selected: false } : node,
      );
      nodesRef.current = nextNodes;
      setNodes(nextNodes);
    }
    if (edgesRef.current.some((edge) => edge.selected)) {
      const nextEdges = edgesRef.current.map((edge) =>
        edge.selected ? { ...edge, selected: false } : edge,
      );
      edgesRef.current = nextEdges;
      setEdges(nextEdges);
    }
    setSelectedId(null);
  };

  const clearSelection = () => {
    releaseSelection();
    setPicker(null);
  };

  const openFullCatalog = () => {
    if (picker?.kind === "catalog") {
      setPicker(null);
      return;
    }
    releaseSelection();
    setPicker({ kind: "catalog" });
  };

  const selected = nodes.find((node) => node.id === selectedId) ?? null;
  const selectedSpec = catalog.find((item) => item.type === selected?.data.nodeType);
  const problemLines =
    selected == null
      ? []
      : problems
          .filter((problem) => problem.node_id === selected.id)
          .map((problem) => formatGraphProblem(t, problem));
  const showCatalog = picker !== null && selected == null;
  const catalogSpecs = picker?.kind === "connect" ? picker.specs : catalog;
  const catalogTitle =
    picker?.kind === "connect" ? t("channels.canvas.nextStep") : t("channels.canvas.palette");

  const chooseSpec = (spec: NodeTypeSpec) => {
    if (picker?.kind === "connect") {
      placeNode(spec, picker.position, {
        sourceId: picker.sourceId,
        sourceHandle: picker.sourceHandle,
      });
      return;
    }
    placeNode(spec, openPosition());
  };

  return (
    <Stack gap="xs" flex={1} mih={0} w="100%">
        <Group justify="space-between">
          <Group gap="xs">
            <Button
              type="button"
              variant="default"
              size="compact-sm"
              disabled={!editable}
              aria-expanded={picker?.kind === "catalog"}
              onClick={openFullCatalog}
            >
              {t("channels.canvas.add")}
            </Button>
            <Tooltip label={t("channels.canvas.undo")}>
              <ActionIcon
                type="button"
                variant="default"
                size="sm"
                aria-label={t("channels.canvas.undo")}
                disabled={!editable || !canUndo}
                onClick={undo}
              >
                <HistoryIcon direction="undo" />
              </ActionIcon>
            </Tooltip>
            <Tooltip label={t("channels.canvas.redo")}>
              <ActionIcon
                type="button"
                variant="default"
                size="sm"
                aria-label={t("channels.canvas.redo")}
                disabled={!editable || !canRedo}
                onClick={redo}
              >
                <HistoryIcon direction="redo" />
              </ActionIcon>
            </Tooltip>
          </Group>
          <Group gap="sm">
            {problems.length > 0 ? (
              <Popover
                opened={problemsOpen}
                onChange={setProblemsOpen}
                position="bottom-end"
                withinPortal
              >
                <Popover.Target>
                  <Button
                    type="button"
                    variant="subtle"
                    color="red"
                    size="compact-sm"
                    aria-expanded={problemsOpen}
                    onClick={() => setProblemsOpen((open) => !open)}
                  >
                    {t("channels.canvas.problems", { n: problems.length })}
                  </Button>
                </Popover.Target>
                <Popover.Dropdown>
                  <Stack gap={4}>
                    {problems.map((problem) => {
                      const label = formatGraphProblem(t, problem);
                      const key = `${problem.code}-${problem.node_id ?? ""}-${problem.edge_id ?? ""}`;
                      if (!problem.node_id && !problem.edge_id) {
                        return (
                          <Text key={key} c="red" size="sm">
                            {label}
                          </Text>
                        );
                      }
                      return (
                        <Button
                          key={key}
                          type="button"
                          variant="subtle"
                          color="red"
                          size="compact-sm"
                          justify="flex-start"
                          onClick={() => {
                            onFocusProblem(problem);
                            setProblemsOpen(false);
                          }}
                        >
                          {label}
                        </Button>
                      );
                    })}
                  </Stack>
                </Popover.Dropdown>
              </Popover>
            ) : null}
          </Group>
        </Group>
        <CanvasEditableContext.Provider value={editable}>
        <CanvasCatalogContext.Provider value={catalog}>
        <div ref={flowRootRef} className="channel-canvas-stage">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={{ type: CHANNEL_EDGE_TYPE }}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onConnectEnd={onConnectEnd}
            onPaneClick={clearSelection}
            isValidConnection={isValidConnection}
            nodesDraggable={editable}
            nodesConnectable={editable}
            elementsSelectable
            multiSelectionKeyCode={null}
            deleteKeyCode={editable ? ["Backspace", "Delete"] : null}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
          {showCatalog || selected ? (
            <Paper
              withBorder
              shadow="md"
              p="sm"
              className="channel-node-config"
              onPointerDown={(event) => event.stopPropagation()}
            >
              {showCatalog ? (
                <>
                  <div className="channel-node-config__header">
                    <Group justify="space-between" align="center" wrap="nowrap" gap="xs">
                      <Text size="sm" fw={600}>
                        {catalogTitle}
                      </Text>
                      <CloseButton
                        size="sm"
                        aria-label={t("channels.node.close")}
                        onClick={clearSelection}
                      />
                    </Group>
                  </div>
                  <div className="channel-node-config__body">
                    <Stack gap={4}>
                      {catalogSpecs.map((spec) => (
                        <Button
                          key={spec.type}
                          type="button"
                          className="channel-node-picker__option"
                          variant="subtle"
                          size="xs"
                          justify="flex-start"
                          onClick={() => chooseSpec(spec)}
                        >
                          <span className="channel-node-picker__copy">
                            <span className="channel-node-picker__label">
                              {nodeTypeLabel(t, spec)}
                            </span>
                            <span className="channel-node-picker__summary">
                              {nodeTypeSummary(t, spec)}
                            </span>
                          </span>
                        </Button>
                      ))}
                    </Stack>
                  </div>
                </>
              ) : selected ? (
                <NodeConfigPanel
                  nodeId={selected.id}
                  data={selected.data}
                  spec={selectedSpec ?? null}
                  schema={(selectedSpec?.config_schema as SchemaObject | undefined) ?? null}
                  editable={editable}
                  problemLines={problemLines}
                  onClose={clearSelection}
                  onChange={(nodeId, data) => {
                    const next = nodesRef.current.map((node) =>
                      node.id === nodeId ? { ...node, data } : node,
                    );
                    nodesRef.current = next;
                    setNodes(next);
                    emit(next, edgesRef.current);
                    commitNow();
                  }}
                />
              ) : null}
            </Paper>
          ) : null}
        </div>
        </CanvasCatalogContext.Provider>
        </CanvasEditableContext.Provider>
    </Stack>
  );

  function paintProblems(currentNodes: ChannelNode[], currentEdges: Edge[]) {
    return {
      nodes: currentNodes.map((node) => ({
        ...node,
        data: { ...node.data, problem: problemNodeIdsRef.current.has(node.id) },
      })),
      edges: channelEdges(
        currentEdges.map((edge) => ({
          ...edge,
          style: problemEdgeIdsRef.current.has(edge.id)
            ? { stroke: PROBLEM_STROKE }
            : undefined,
        })),
      ),
    };
  }

  function isValidConnection(connection: Connection | Edge) {
    if (!editable) return false;
    return connectionAllowed(graphNow(), catalog, connection);
  }
}

function snapshotOf(nodes: ChannelNode[], edges: Edge[]): CanvasSnapshot {
  return {
    nodes: nodes.map((node) => ({
      ...node,
      position: { ...node.position },
      selected: Boolean(node.selected),
      data: {
        ...node.data,
        problem: false,
        config: { ...node.data.config },
        retry: node.data.retry ? { ...node.data.retry } : null,
      },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
      selected: Boolean(edge.selected),
    })),
  };
}

function sameSnapshot(left: CanvasSnapshot, right: CanvasSnapshot): boolean {
  return JSON.stringify(structural(left)) === JSON.stringify(structural(right));
}

function structural(snap: CanvasSnapshot) {
  return {
    nodes: snap.nodes.map((node) => ({
      id: node.id,
      x: node.position.x,
      y: node.position.y,
      type: node.data.nodeType,
      name: node.data.name,
      config: node.data.config,
      onError: node.data.onError,
      retry: node.data.retry,
      entry: node.data.entry,
    })),
    edges: snap.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    })),
  };
}

function eventPoint(event: MouseEvent | TouchEvent): { x: number; y: number } | null {
  if ("changedTouches" in event) {
    const touch = event.changedTouches[0];
    return touch ? { x: touch.clientX, y: touch.clientY } : null;
  }
  return { x: event.clientX, y: event.clientY };
}

function HistoryIcon({ direction }: { direction: "undo" | "redo" }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={direction === "redo" ? { transform: "scaleX(-1)" } : undefined}
    >
      <path d="M9 14 4 9l5-5" />
      <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

function pointerStillOnEdge(target: EventTarget | null, edgeId: string): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest(".react-flow__edge")?.getAttribute("data-id") === edgeId) return true;
  if (target.closest(".react-flow__edge-toolbar")?.getAttribute("data-id") === edgeId) return true;
  return target.closest(".channel-flow-edge__delete")?.getAttribute("data-edge-id") === edgeId;
}

function channelEdges(edges: Edge[]): Edge[] {
  if (edges.every((edge) => edge.type === CHANNEL_EDGE_TYPE)) return edges;
  return edges.map((edge) =>
    edge.type === CHANNEL_EDGE_TYPE ? edge : { ...edge, type: CHANNEL_EDGE_TYPE },
  );
}

function ChannelFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  style,
  markerEnd,
  markerStart,
  interactionWidth,
  deletable = true,
}: EdgeProps) {
  const t = useTranslate();
  const editable = useContext(CanvasEditableContext);
  const { deleteElements } = useReactFlow();
  const [hovered, setHovered] = useState(false);
  const hideTimer = useRef<number | null>(null);
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  useEffect(
    () => () => {
      if (hideTimer.current != null) window.clearTimeout(hideTimer.current);
    },
    [],
  );

  const enter = () => {
    if (hideTimer.current != null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    setHovered(true);
  };

  const leave = (event: { relatedTarget: EventTarget | null }) => {
    if (pointerStillOnEdge(event.relatedTarget, id)) return;
    if (hideTimer.current != null) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      setHovered(false);
    }, 80);
  };

  const visible = editable && deletable && (Boolean(selected) || hovered);

  return (
    <>
      <g onMouseEnter={enter} onMouseLeave={leave}>
        <BaseEdge
          id={id}
          path={path}
          style={style}
          markerEnd={markerEnd}
          markerStart={markerStart}
          interactionWidth={interactionWidth}
        />
      </g>
      {visible ? (
        <EdgeToolbar
          edgeId={id}
          x={labelX}
          y={labelY}
          isVisible
          className="nodrag nopan"
        >
          <button
            type="button"
            className="channel-flow-edge__delete nodrag nopan"
            data-edge-id={id}
            aria-label={t("channels.node.delete")}
            onMouseEnter={enter}
            onMouseLeave={leave}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              void deleteElements({ edges: [{ id }] });
            }}
          >
            <CloseIcon />
          </button>
        </EdgeToolbar>
      ) : null}
    </>
  );
}

function ChannelFlowNode({ id, data, selected }: NodeProps<ChannelNode>) {
  const t = useTranslate();
  const editable = useContext(CanvasEditableContext);
  const catalog = useContext(CanvasCatalogContext);
  const spec = catalog.find((item) => item.type === data.nodeType);
  const { deleteElements } = useReactFlow();
  const errorAnchor = catalog.some(
    (item) => item.type === data.nodeType && item.outputs.some((port) => port.port === "error"),
  );
  const emphasis = data.problem
    ? "channel-flow-node--problem"
    : selected
      ? "channel-flow-node--selected"
      : "";
  return (
    <div
      className={emphasis ? `channel-flow-node ${emphasis}` : "channel-flow-node"}
      style={{
        minWidth: 148,
        padding: "8px 12px",
        borderRadius: 8,
        background: "var(--mantine-color-body)",
      }}
    >
      {editable ? (
        <button
          type="button"
          className="channel-flow-node__delete nodrag nopan"
          aria-label={t("channels.node.delete")}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            void deleteElements({ nodes: [{ id }] });
          }}
        >
          <CloseIcon />
        </button>
      ) : null}
      {data.entry ? null : <Handle type="target" position={Position.Left} id="main" />}
      <Text size="xs" c="dimmed">
        {spec ? nodeTypeLabel(t, spec) : data.nodeType}
      </Text>
      <Text size="sm" fw={600}>
        {data.name}
      </Text>
      <Handle type="source" position={Position.Right} id="main" />
      {errorAnchor ? (
        <Handle
          type="source"
          position={Position.Bottom}
          id="error"
          isConnectable={false}
          isConnectableStart={false}
          isConnectableEnd={false}
          style={{
            width: 0,
            height: 0,
            minWidth: 0,
            minHeight: 0,
            opacity: 0,
            border: "none",
            pointerEvents: "none",
          }}
        />
      ) : null}
    </div>
  );
}
