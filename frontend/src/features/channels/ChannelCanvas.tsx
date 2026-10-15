"use client";

import { Button, CloseButton, Group, Paper, Popover, Stack, Text } from "@mantine/core";
import { usePermissions, useTranslate } from "@refinedev/core";
import {
  Background,
  BaseEdge,
  ControlButton,
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
import {
  Fragment,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

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
  nodeRef,
  graphFromFlow,
  newGraphId,
  outputTargetTypes,
  type FlowNodeData,
} from "@/features/channels/graphValidation";
import { NodeConfigPanel } from "@/features/channels/NodeConfigPanel";
import { ResultRegion, UpstreamRegion } from "@/features/channels/NodeRunRegions";
import {
  executionCountByNode,
  phaseByNode,
  samplesByNode,
  type NodeRunPhase,
} from "@/features/channels/runSession";
import type { ChannelTemplatePreview } from "@/features/channels/TemplateRunPreview";
import { canAuthorNodeType } from "@/features/channels/nodePermission";
import { nodeTypeLabel, nodeTypeSummary } from "@/features/channels/nodeTypeCopy";
import {
  isLoopReturn,
  layoutNodePorts,
  returnEdgePath,
  type HandleSide,
  type PortPlacement,
} from "@/features/channels/portLayout";
import {
  formatGraphProblem,
  problemColor,
  problemIdentity,
  type ProblemGraph,
} from "@/features/channels/problemLabel";
import { upstreamOutputs } from "@/features/channels/templateLogic";
import type {
  ChannelRunDetail,
  ExpressionContext,
  Graph,
  GraphProblem,
  NodeTypeSpec,
  RefinedPort,
} from "@/features/channels/types";

type ChannelNode = Node<FlowNodeData, "channel">;

type CanvasSnapshot = {
  nodes: ChannelNode[];
  edges: Edge[];
};

type ProblemHighlight = {
  nodeId: string | null;
  edgeId: string | null;
  key: string;
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

const NODE_DRAG_THRESHOLD = 4;
const CHANNEL_EDGE_TYPE = "channel";
const nodeTypes = { channel: ChannelFlowNode };
const edgeTypes = { [CHANNEL_EDGE_TYPE]: ChannelFlowEdge };
const PROBLEM_STROKE = "var(--mantine-color-red-6)";
const PROBLEM_HOVER_CLOSE_MS = 120;

function highlightTargets(problem: GraphProblem, active: ProblemHighlight): boolean {
  return active.nodeId
    ? problem.node_id === active.nodeId
    : problem.edge_id != null && problem.edge_id === active.edgeId;
}
const CanvasSurfaceContext = createContext({ editing: false, mutable: false });
const CanvasCatalogContext = createContext<readonly NodeTypeSpec[]>([]);
const CanvasRunContext = createContext<{
  phases: ReadonlyMap<string, NodeRunPhase>;
  counts: ReadonlyMap<string, number>;
  onRun: (nodeId: string) => void;
}>({ phases: new Map(), counts: new Map(), onRun: () => {} });

type Props = {
  graph: Graph;
  catalog: NodeTypeSpec[];
  /** Edit page keeps authoring chrome. Browse hides it. */
  appearance: "edit" | "browse";
  /** Draft mutations are allowed. A running test keeps the edit appearance and sets this false. */
  mutable: boolean;
  /**
   * Bumps after a draft save so the canvas adopts the stored graph without remounting.
   * Selection, the open side panel, the viewport, and undo history stay.
   */
  adoptToken?: number;
  problems: GraphProblem[];
  ports?: readonly RefinedPort[];
  context?: ExpressionContext | null;
  onChange: (graph: Graph) => void;
  sessionRun?: ChannelRunDetail | null;
  /** Null hides the template previews. */
  templatePreview?: ChannelTemplatePreview | null;
  onRun?: (nodeId: string) => void;
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
  appearance,
  mutable,
  adoptToken = 0,
  problems,
  ports = [],
  context = null,
  onChange,
  sessionRun = null,
  templatePreview = null,
  onRun = () => {},
}: Props) {
  const t = useTranslate();
  const { data: heldPermissions } = usePermissions<string[]>({});
  const { screenToFlowPosition, setCenter, getInternalNode } = useReactFlow();
  const entryTypes = useMemo(
    () => new Set(catalog.filter((item) => item.entry).map((item) => item.type)),
    [catalog],
  );
  const initial = useMemo(
    () => flowFromGraph(graph, entryTypes),
    // The canvas owns edits after mount. The parent remounts only when a draft is loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const seededNodes = initial.nodes.map((node) => ({ ...node, type: "channel" as const }));
  const seededEdges = channelEdges(initial.edges);
  const [nodes, setNodes] = useState<ChannelNode[]>(seededNodes);
  const [edges, setEdges] = useState<Edge[]>(seededEdges);
  const [configNodeId, setConfigNodeId] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerState | null>(null);
  const [highlight, setHighlight] = useState<ProblemHighlight | null>(null);
  const [problemsDismissed, setProblemsDismissed] = useState(0);
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
  const highlightRef = useRef<ProblemHighlight | null>(highlight);
  nodesRef.current = nodes;
  edgesRef.current = edges;
  highlightRef.current = highlight;
  const settingsRef = useRef(graph.settings);
  settingsRef.current = graph.settings;

  const problemKey = problems.map((problem) => problemIdentity(problem)).join("|");
  const highlightKey = highlight?.key ?? "";
  useEffect(() => {
    const active = highlightRef.current;
    const resolved =
      active != null && !problems.some((problem) => highlightTargets(problem, active))
        ? null
        : active;
    if (active && resolved == null) {
      highlightRef.current = null;
      setHighlight(null);
    }
    const painted = paintProblems(nodesRef.current, edgesRef.current, resolved);
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
    // problemKey and highlightKey are the stable digests. The arrays themselves are new each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemKey, highlightKey]);

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
    setConfigNodeId(painted.nodes.find((node) => node.selected)?.id ?? null);
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

  const adoptedToken = useRef(adoptToken);
  useEffect(() => {
    if (adoptedToken.current === adoptToken) return;
    adoptedToken.current = adoptToken;
    const nextGraph = graph;
    if (JSON.stringify(graphNow()) === JSON.stringify(nextGraph)) return;
    const selectedNodeIds = new Set(
      nodesRef.current.filter((node) => node.selected).map((node) => node.id),
    );
    const selectedEdgeIds = new Set(
      edgesRef.current.filter((edge) => edge.selected).map((edge) => edge.id),
    );
    const flow = flowFromGraph(nextGraph, entryTypes);
    const adoptedNodes: ChannelNode[] = flow.nodes.map((node) => ({
      ...node,
      type: "channel",
      selected: selectedNodeIds.has(node.id),
    }));
    const adoptedEdges = channelEdges(
      flow.edges.map((edge) => ({
        ...edge,
        selected: selectedEdgeIds.has(edge.id),
      })),
    );
    const painted = paintProblems(adoptedNodes, adoptedEdges);
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
    setConfigNodeId((current) =>
      current != null && painted.nodes.some((node) => node.id === current) ? current : null,
    );
    // The stored graph is one undo step ahead of the pre-save canvas, so undo
    // returns to that unsaved graph.
    pushSnap();
  }, [adoptToken, entryTypes, graph]);

  useEffect(() => {
    if (mutable) return;
    setPicker(null);
  }, [mutable]);

  useEffect(() => {
    if (!mutable) return;
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
  }, [mutable]);

  const clearHighlight = () => {
    if (highlightRef.current == null) return;
    highlightRef.current = null;
    setHighlight(null);
    const painted = paintProblems(nodesRef.current, edgesRef.current, null);
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
  };

  const centerOnHighlight = (active: ProblemHighlight) => {
    const centerOf = (nodeId: string) => {
      const node = getInternalNode(nodeId);
      if (!node) return null;
      return {
        x: node.internals.positionAbsolute.x + (node.measured.width ?? 0) / 2,
        y: node.internals.positionAbsolute.y + (node.measured.height ?? 0) / 2,
      };
    };
    if (active.nodeId) {
      const center = centerOf(active.nodeId);
      if (center) void setCenter(center.x, center.y, { duration: 200 });
      return;
    }
    if (!active.edgeId) return;
    const edge = edgesRef.current.find((item) => item.id === active.edgeId);
    if (!edge) return;
    const source = centerOf(edge.source);
    const target = centerOf(edge.target);
    if (!source || !target) return;
    void setCenter((source.x + target.x) / 2, (source.y + target.y) / 2, { duration: 200 });
  };

  const focusProblem = (problem: GraphProblem) => {
    if (!problem.node_id && !problem.edge_id) return;
    const next: ProblemHighlight = {
      nodeId: problem.node_id,
      edgeId: problem.node_id ? null : problem.edge_id,
      key: problemIdentity(problem),
    };
    highlightRef.current = next;
    setHighlight(next);
    const painted = paintProblems(
      nodesRef.current.map((node) => ({
        ...node,
        selected: next.nodeId != null && node.id === next.nodeId,
      })),
      edgesRef.current.map((edge) => ({
        ...edge,
        selected: next.edgeId != null && edge.id === next.edgeId,
      })),
      next,
    );
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
    setConfigNodeId(next.nodeId);
    setPicker(null);
    centerOnHighlight(next);
  };

  const placeNode = (
    spec: NodeTypeSpec,
    position: { x: number; y: number },
    link?: { sourceId: string; sourceHandle: string },
  ) => {
    if (!mutable || !canAuthorNodeType(spec.permission, heldPermissions)) return;
    clearHighlight();
    const label = nodeTypeLabel(t, spec);
    const count = nodesRef.current.filter((node) => node.data.nodeType === spec.type).length;
    const name = count === 0 ? label : `${label} ${count + 1}`;
    const id = newGraphId("nd");
    const ref = nodeRef(
      spec.type,
      nodesRef.current.map((node) => node.data.ref),
    );
    const created: ChannelNode = {
      id,
      type: "channel",
      position,
      selected: true,
      data: emptyNodeData(
        spec.type,
        ref,
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
    setConfigNodeId(id);
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
    setConfigNodeId((current) => {
      if (current == null) return null;
      const open = next.find((node) => node.id === current);
      return open?.selected ? current : null;
    });
    const marked = highlightRef.current;
    if (marked && selected && selected.id !== marked.nodeId) clearHighlight();
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
    const marked = highlightRef.current;
    if (marked && selected && selected.id !== marked.edgeId) clearHighlight();
    if (selected) {
      setConfigNodeId(null);
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
    if (!connectionAllowed(graphNow(), catalog, connection)) return;
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
    if (!mutable || connectionState.isValid === true) return;
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
    setConfigNodeId(null);
  };

  const clearSelection = () => {
    releaseSelection();
    clearHighlight();
    setPicker(null);
    setProblemsDismissed((count) => count + 1);
  };

  const openFullCatalog = () => {
    if (picker?.kind === "catalog") {
      setPicker(null);
      return;
    }
    releaseSelection();
    setPicker({ kind: "catalog" });
  };

  const selected = nodes.find((node) => node.id === configNodeId) ?? null;
  const selectedSpec = catalog.find((item) => item.type === selected?.data.nodeType);
  const labelGraph = problemGraphOf(nodes, edges);
  const revealKey =
    selected != null && highlight?.nodeId === selected.id ? highlight.key : null;
  const outputSchemas = new Map<string, SchemaObject | null>();
  for (const port of ports) {
    if (port.direction !== "output") continue;
    outputSchemas.set(`${port.node_id}:${port.port}`, port.schema);
    if (port.port === "main") outputSchemas.set(port.node_id, port.schema);
  }
  const samples = useMemo(
    () => (sessionRun ? samplesByNode(sessionRun.node_executions) : new Map<string, unknown>()),
    [sessionRun],
  );
  const phases = useMemo(
    () => (sessionRun ? phaseByNode(sessionRun, sessionRun.graph ?? graph) : new Map()),
    [sessionRun, graph],
  );
  const counts = useMemo(
    () =>
      sessionRun
        ? executionCountByNode(sessionRun.node_executions)
        : new Map<string, number>(),
    [sessionRun],
  );
  const showCatalog = picker !== null && selected == null;
  const hasTrigger = nodes.some((node) => node.data.entry);
  const catalogSpecs = (picker?.kind === "connect" ? picker.specs : catalog).filter(
    (spec) => !hasTrigger || !spec.entry,
  );
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

  const openNodeConfig = (nodeId: string) => {
    setConfigNodeId(nodeId);
    setPicker(null);
    const marked = highlightRef.current;
    if (marked && marked.nodeId !== nodeId) clearHighlight();
  };

  const onCanvasKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter") return;
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.classList.contains("react-flow__node")) return;
    const nodeId = target.getAttribute("data-id");
    if (!nodeId) return;
    openNodeConfig(nodeId);
  };

  return (
    <Stack gap={0} flex={1} mih={0} h="100%" w="100%" pos="relative">
        <CanvasSurfaceContext.Provider value={{ editing: appearance === "edit", mutable }}>
        <CanvasCatalogContext.Provider value={catalog}>
        <CanvasRunContext.Provider value={{ phases, counts, onRun }}>
        <div
          ref={flowRootRef}
          className={
            appearance === "edit"
              ? "channel-canvas-stage"
              : "channel-canvas-stage channel-canvas-stage--browse"
          }
          onKeyDown={onCanvasKeyDown}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges.map((edge) => ({
              ...edge,
              ariaLabel: t("channels.canvas.edge", {
                source: portLabel(t, edge.sourceHandle || "main"),
                target: portLabel(t, edge.targetHandle || "main"),
              }),
              className: [
                edge.className,
                isLoopReturn(edge.targetHandle) ? "channel-flow-edge--return" : "",
              ]
                .filter(Boolean)
                .join(" ") || undefined,
            }))}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={{ type: CHANNEL_EDGE_TYPE }}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => openNodeConfig(node.id)}
            onConnect={onConnect}
            onConnectEnd={onConnectEnd}
            onPaneClick={clearSelection}
            isValidConnection={isValidConnection}
            nodesDraggable={mutable}
            nodesConnectable={mutable}
            elementsSelectable
            nodeDragThreshold={NODE_DRAG_THRESHOLD}
            nodeClickDistance={NODE_DRAG_THRESHOLD}
            multiSelectionKeyCode={null}
            deleteKeyCode={mutable ? ["Backspace", "Delete"] : null}
            fitView
          >
            {appearance === "edit" ? <Background /> : null}
            <Controls
              showZoom={false}
              showInteractive={appearance === "edit" && mutable}
              className="channel-canvas-controls"
            >
              {problems.length > 0 ? (
                <ProblemsControl
                  problems={problems}
                  graph={labelGraph}
                  activeKey={highlight?.key ?? null}
                  dismissToken={problemsDismissed}
                  onFocus={focusProblem}
                />
              ) : null}
              {appearance === "edit" ? (
                <ControlButton
                  className="channel-canvas-add"
                  title={t("channels.canvas.add")}
                  aria-label={t("channels.canvas.add")}
                  aria-expanded={picker?.kind === "catalog"}
                  disabled={!mutable}
                  onClick={openFullCatalog}
                >
                  <PlusIcon />
                </ControlButton>
              ) : null}
              {appearance === "edit" ? (
                <ControlButton
                  className="channel-canvas-undo"
                  title={t("channels.canvas.undo")}
                  aria-label={t("channels.canvas.undo")}
                  disabled={!mutable || !canUndo}
                  onClick={undo}
                >
                  <HistoryIcon direction="undo" />
                </ControlButton>
              ) : null}
              {appearance === "edit" ? (
                <ControlButton
                  className="channel-canvas-redo"
                  title={t("channels.canvas.redo")}
                  aria-label={t("channels.canvas.redo")}
                  disabled={!mutable || !canRedo}
                  onClick={redo}
                >
                  <HistoryIcon direction="redo" />
                </ControlButton>
              ) : null}
            </Controls>
          </ReactFlow>
          {showCatalog || selected ? (
            <Paper
              withBorder
              shadow="md"
              p="sm"
              className={
                selected
                  ? "channel-node-config channel-node-config--detail"
                  : "channel-node-config"
              }
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
                      {catalogSpecs.map((spec) => {
                        const allowed = canAuthorNodeType(spec.permission, heldPermissions);
                        const reason =
                          !allowed && spec.permission
                            ? t("channels.canvas.permissionRequired", {
                                permission: spec.permission,
                              })
                            : "";
                        return (
                          <Button
                            key={spec.type}
                            type="button"
                            className="channel-node-picker__option"
                            variant="subtle"
                            size="xs"
                            justify="flex-start"
                            disabled={!allowed}
                            title={reason || undefined}
                            onClick={() => {
                              if (!allowed) return;
                              chooseSpec(spec);
                            }}
                          >
                            <span className="channel-node-picker__copy">
                              <span className="channel-node-picker__label">
                                {nodeTypeLabel(t, spec)}
                              </span>
                              <span className="channel-node-picker__summary">
                                {nodeTypeSummary(t, spec)}
                              </span>
                              {reason ? (
                                <span className="channel-node-picker__summary">{reason}</span>
                              ) : null}
                            </span>
                          </Button>
                        );
                      })}
                    </Stack>
                  </div>
                </>
              ) : selected ? (
                <NodeConfigPanel
                  nodeId={selected.id}
                  data={selected.data}
                  spec={selectedSpec ?? null}
                  schema={(selectedSpec?.config_schema as SchemaObject | undefined) ?? null}
                  editable={mutable}
                  canRun={appearance === "edit" ? mutable : null}
                  revealKey={revealKey}
                  problems={problems.filter((problem) => problem.node_id === selected.id)}
                  graph={labelGraph}
                  scope={{
                    nodes: upstreamOutputs(
                      selected.id,
                      nodes.map((node) => ({ id: node.id, ref: node.data.ref, name: node.data.name })),
                      edges.map((edge) => ({
                        source: edge.source,
                        target: edge.target,
                        sourcePort: edge.sourceHandle ?? undefined,
                        targetPort: edge.targetHandle ?? undefined,
                      })),
                      outputSchemas,
                      samples,
                    ),
                    context: {
                      channel: context?.channel ?? null,
                      run: context?.run ?? null,
                      platform: context?.platform ?? null,
                    },
                  }}
                  templatePreview={templatePreview}
                  upstream={
                    <UpstreamRegion
                      nodeId={selected.id}
                      nodes={nodes.map((node) => ({
                        id: node.id,
                        name: node.data.name,
                        ref: node.data.ref,
                      }))}
                      hasUpstream={edges.some((edge) => edge.target === selected.id)}
                      detail={sessionRun}
                    />
                  }
                  result={<ResultRegion nodeId={selected.id} detail={sessionRun} />}
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
                  onRun={onRun}
                />
              ) : null}
            </Paper>
          ) : null}
        </div>
        </CanvasRunContext.Provider>
        </CanvasCatalogContext.Provider>
        </CanvasSurfaceContext.Provider>
    </Stack>
  );

  function paintProblems(
    currentNodes: ChannelNode[],
    currentEdges: Edge[],
    active: ProblemHighlight | null = highlightRef.current,
  ) {
    return {
      nodes: currentNodes.map((node) => ({
        ...node,
        data: { ...node.data, problem: active?.nodeId === node.id },
      })),
      edges: channelEdges(
        currentEdges.map((edge) => ({
          ...edge,
          style: active?.edgeId === edge.id ? { stroke: PROBLEM_STROKE } : undefined,
        })),
      ),
    };
  }

  function isValidConnection(connection: Connection | Edge) {
    if (!mutable) return false;
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

function problemGraphOf(nodes: ChannelNode[], edges: Edge[]): ProblemGraph {
  return {
    nodes: nodes.map((node) => ({ id: node.id, name: node.data.name })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: { node_id: edge.source },
      target: { node_id: edge.target },
    })),
  };
}

function ProblemsControl({
  problems,
  graph,
  activeKey,
  dismissToken,
  onFocus,
}: {
  problems: GraphProblem[];
  graph: ProblemGraph;
  activeKey: string | null;
  dismissToken: number;
  onFocus: (problem: GraphProblem) => void;
}) {
  const t = useTranslate();
  const [pinned, setPinned] = useState(false);
  const [hovered, setHovered] = useState(false);
  const hideTimer = useRef<number | null>(null);
  const previousCount = useRef(0);
  const [pulseToken, setPulseToken] = useState(0);
  const seenDismiss = useRef(dismissToken);

  useEffect(() => {
    if (seenDismiss.current === dismissToken) return;
    seenDismiss.current = dismissToken;
    setPinned(false);
  }, [dismissToken]);

  useEffect(() => {
    if (problems.length > previousCount.current) {
      setPulseToken((token) => token + 1);
    }
    previousCount.current = problems.length;
  }, [problems.length]);

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

  const leave = () => {
    if (hideTimer.current != null) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      setHovered(false);
    }, PROBLEM_HOVER_CLOSE_MS);
  };

  const open = pinned || hovered;
  const errorCount = problems.filter((problem) => problem.severity !== "warning").length;
  const warningCount = problems.length - errorCount;
  const warningsOnly = errorCount === 0;
  const label = t("channels.canvas.problemsSummary", {
    errors: errorCount,
    warnings: warningCount,
  });

  return (
    <Popover
      opened={open}
      onChange={(next) => {
        if (!next) setPinned(false);
      }}
      position="right-end"
      withinPortal
    >
      <Popover.Target>
        <ControlButton
          className={
            warningsOnly
              ? "channel-canvas-problems channel-canvas-problems--warning"
              : "channel-canvas-problems"
          }
          title={label}
          aria-label={label}
          aria-expanded={open}
          onClick={() => setPinned((current) => !current)}
          onMouseEnter={enter}
          onMouseLeave={leave}
        >
          {pulseToken > 0 ? (
            <span key={pulseToken} className="channel-canvas-problems__pulse" />
          ) : null}
          <WarningIcon />
          <span className="channel-canvas-problems__badge">{problems.length}</span>
        </ControlButton>
      </Popover.Target>
      <Popover.Dropdown onMouseEnter={enter} onMouseLeave={leave}>
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            {label}
          </Text>
          {problems.map((problem) => {
            const itemLabel = formatGraphProblem(t, problem, graph);
            const key = problemIdentity(problem);
            const color = problemColor(problem.severity);
            const tone =
              color === "yellow" ? "channel-canvas-problems__item--warning" : undefined;
            if (!problem.node_id && !problem.edge_id) {
              return (
                <Text key={key} c={color} className={tone} size="sm">
                  {itemLabel}
                </Text>
              );
            }
            const active = key === activeKey;
            return (
              <Button
                key={key}
                type="button"
                variant="subtle"
                color={color}
                size="compact-sm"
                justify="flex-start"
                className={[tone, active ? "channel-canvas-problems__item--active" : undefined]
                  .filter(Boolean)
                  .join(" ") || undefined}
                aria-current={active ? "true" : undefined}
                onClick={() => onFocus(problem)}
              >
                {itemLabel}
              </Button>
            );
          })}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

function WarningIcon() {
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
    >
      <path d="M10.3 4.3 2.4 18a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
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

function PlayIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
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
  targetHandleId,
  selected,
  style,
  markerEnd,
  markerStart,
  interactionWidth,
  deletable = true,
}: EdgeProps) {
  const t = useTranslate();
  const { editing, mutable } = useContext(CanvasSurfaceContext);
  const { deleteElements } = useReactFlow();
  const [hovered, setHovered] = useState(false);
  const hideTimer = useRef<number | null>(null);
  const [path, labelX, labelY] = isLoopReturn(targetHandleId)
    ? (() => {
        const routed = returnEdgePath(sourceX, sourceY, targetX, targetY);
        return [routed.path, routed.labelX, routed.labelY] as const;
      })()
    : getBezierPath({
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

  const visible = editing && deletable && (Boolean(selected) || hovered);

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
            disabled={!mutable}
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
  const { editing, mutable } = useContext(CanvasSurfaceContext);
  const catalog = useContext(CanvasCatalogContext);
  const spec = catalog.find((item) => item.type === data.nodeType);
  const { deleteElements } = useReactFlow();
  const inputs = spec ? spec.inputs : data.entry ? [] : [{ port: "main", description: "" }];
  const outputs = spec ? spec.outputs : [{ port: "main", description: "" }];
  const laid = layoutNodePorts(inputs, outputs);
  const errorAnchor = outputs.some((port) => port.port === "error");
  const run = useContext(CanvasRunContext);
  const phase = run.phases.get(id);
  const count = run.counts.get(id) ?? 0;
  const onRun = run.onRun;
  const depth = Math.max(
    laid.inputs.filter((port) => port.position !== "bottom").length,
    laid.outputs.length,
    1,
  );
  const emphasis = data.problem
    ? "channel-flow-node--problem"
    : selected
      ? "channel-flow-node--selected"
      : "";
  const className = [
    "channel-flow-node",
    emphasis,
    phase ? `channel-flow-node--${phase}` : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div
      className={className}
      style={{
        minWidth: 148,
        minHeight: depth > 1 ? 24 + depth * 28 : undefined,
        padding: "8px 12px",
        borderRadius: 8,
        background: "var(--mantine-color-body)",
      }}
    >
      {editing ? (
        <>
          <button
            type="button"
            className="channel-flow-node__run nodrag nopan"
            aria-label={t("channels.node.run")}
            title={t("channels.node.run")}
            disabled={!mutable}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onRun(id);
            }}
          >
            <PlayIcon />
          </button>
          <button
            type="button"
            className="channel-flow-node__delete nodrag nopan"
            aria-label={t("channels.node.delete")}
            disabled={!mutable}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              void deleteElements({ nodes: [{ id }] });
            }}
          >
            <CloseIcon />
          </button>
        </>
      ) : null}
      <PortHandles ports={laid.inputs} nodeName={data.name} kind="target" />
      <Text size="xs" c="dimmed">
        {spec ? nodeTypeLabel(t, spec) : data.nodeType}
      </Text>
      <Text size="sm" fw={600}>
        {data.name}
      </Text>
      {count > 1 ? (
        <Text size="xs" c="dimmed" className="channel-flow-node__count">
          {t("channels.run.executions", { count })}
        </Text>
      ) : null}
      {phase === "dead" ? (
        <Text size="xs" c="dimmed" className="channel-flow-node__status">
          {t("channels.run.notRun")}
        </Text>
      ) : null}
      <PortHandles ports={laid.outputs} nodeName={data.name} kind="source" />
      {errorAnchor ? (
        <Handle
          type="source"
          position={Position.Bottom}
          id="error"
          aria-hidden
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

function PortHandles({
  ports,
  nodeName,
  kind,
}: {
  ports: readonly PortPlacement[];
  nodeName: string;
  kind: "target" | "source";
}) {
  const t = useTranslate();
  return (
    <>
      {ports.map((port) => {
        const name = portLabel(t, port.port);
        return (
          <Fragment key={`${kind}-${port.port}`}>
            <Handle
              type={kind}
              position={flowPosition(port.position)}
              id={port.port}
              className={port.loopBack ? "channel-flow-handle--loop" : undefined}
              style={port.position === "bottom" ? { left: "50%" } : { top: port.top }}
              aria-label={t("channels.canvas.handle", {
                node: nodeName,
                port: name,
                side: t(kind === "target" ? "channels.canvas.input" : "channels.canvas.output"),
              })}
              role="button"
            />
            {port.labelled ? (
              <span
                className={`channel-flow-port channel-flow-port--${port.position}`}
                style={port.position === "bottom" ? undefined : { top: port.top }}
              >
                {name}
              </span>
            ) : null}
          </Fragment>
        );
      })}
    </>
  );
}

function flowPosition(side: HandleSide): Position {
  if (side === "left") return Position.Left;
  if (side === "right") return Position.Right;
  return Position.Bottom;
}

function portLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  port: string,
): string {
  const key = `channels.canvas.ports.${port}`;
  const text = t(key, { defaultValue: "" });
  if (!text || text === key) return port;
  return text;
}
