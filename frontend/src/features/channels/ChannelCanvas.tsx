"use client";

import {
  ActionIcon,
  Button,
  Menu,
  Paper,
  Stack,
  Text,
  Tooltip,
  useComputedColorScheme,
} from "@mantine/core";
import { usePermissions, useTranslate } from "@refinedev/core";
import {
  Background,
  BaseEdge,
  EdgeToolbar,
  Handle,
  MarkerType,
  NodeResizer,
  NodeToolbar,
  Position,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  ViewportPortal,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  getBezierPath,
  useReactFlow,
  useStoreApi,
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
  useLayoutEffect,
  useCallback,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import "@xyflow/react/dist/style.css";
import "./ChannelCanvas.css";

import { EmptyState } from "@/components/feedback/EmptyState";
import { presentConsoleNotification } from "@/providers/notification-provider";
import { CanvasToolbar } from "@/features/channels/CanvasToolbar";
import { formatShortcutChord, type ShortcutChord } from "@/features/channels/CanvasShortcuts";
import {
  parseFragment,
  pasteFragment,
  serializeFragment,
  type PasteSkip,
} from "@/features/channels/canvasClipboard";
import { canvasShortcutTarget, canvasViewportDuration } from "@/features/channels/useCanvasShortcuts";
import { NodePicker, type PickerEntry } from "@/features/channels/NodePicker";

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
  insertableTypes,
  nodeRef,
  graphFromFlow,
  newGraphId,
  outputTargetTypes,
  type FlowNodeData,
  type FlowNoteShape,
} from "@/features/channels/graphValidation";
import { NodeConfigPanel } from "@/features/channels/NodeConfigPanel";
import { familyTint, nodeTypeIcon } from "@/features/channels/nodeVisual";
import { MOTION_MS } from "@/theme/tokens";
import { listExecutions } from "@/features/channels/api";
import { latestExecutionQuery } from "@/features/channels/datasetView";
import {
  ResultRegion,
  SampleBar,
  UpstreamRegion,
  useNodeSample,
  type RunNodeInfo,
} from "@/features/channels/NodeRunRegions";
import type { PathSegment } from "@/features/channels/RunExecutionOutput";
import {
  executionCountByNode,
  phaseByNode,
  recordedKey,
  scopeRequest,
  type NodeRunPhase,
} from "@/features/channels/runSession";
import type { NodeSampleScopeLevel } from "@/features/channels/types";
import type { ChannelTemplatePreview } from "@/features/channels/TemplateRunPreview";
import { canAuthorNodeType } from "@/features/channels/nodePermission";
import { nodeTypeLabel } from "@/features/channels/nodeTypeCopy";
import {
  EACH_INSET,
  frameBox,
  isContainerNode,
  layoutNodePorts,
  parentsFirst,
  type HandleSide,
  type PortPlacement,
} from "@/features/channels/portLayout";
import {
  presentNodeStatus,
  toneVariable,
  type Tone,
} from "@/components/display/statusTone";
import {
  AdjustmentsIcon,
  CheckIcon,
  CircleDashedIcon,
  ClockIcon,
  CloseIcon,
  CopyIcon,
  CutIcon,
  DuplicateIcon,
  ErrorIcon,
  FitViewIcon,
  LoaderIcon,
  NoteIcon,
  PasteIcon,
  PlayIcon,
} from "@/components/icons";
import { CanvasPlusIcon } from "@/features/channels/CanvasPlusIcon";
import {
  absolutePosition,
  edgesAfterReparent,
  frameLinkAllowed,
  freezeFrames,
  placementFromPort,
  placementOnEdge,
  reparentDrag,
  type FrozenFrame,
  type LinkMember,
} from "@/features/channels/frameLink";
import { problemIdentity, type ProblemGraph } from "@/features/channels/problemLabel";
import { completionSamples, templateInsertion, upstreamOutputs } from "@/features/channels/templateLogic";
import { outputPath } from "@/features/channels/templateScope";
import type { TemplateCaret } from "@/features/channels/TemplateField";
import { useShowInstant } from "@/hooks/useFormatInstant";
import type {
  ChannelRunDetail,
  ExpressionContext,
  Graph,
  GraphProblem,
  NodeExecution,
  NodeTypeSpec,
  RefinedPort,
} from "@/features/channels/types";

type ChannelNode = Node<FlowNodeData, "channel">;
type NoteData = { text: string };
type NoteCanvasNode = Node<NoteData, "note"> & { width: number; height: number };
type CanvasNode = ChannelNode | NoteCanvasNode;

type DragPreview = {
  ids: readonly string[];
  frozen: readonly FrozenFrame[];
};

const NOTE_WIDTH = 240;
const NOTE_HEIGHT = 120;
const NOTE_MIN_WIDTH = 160;
const NOTE_MIN_HEIGHT = 80;
const NOTE_MAX_SIZE = 2000;

function isChannelNode(node: CanvasNode): node is ChannelNode {
  return node.type !== "note";
}

function isNoteNode(node: CanvasNode): node is NoteCanvasNode {
  return node.type === "note";
}

const PORT_PLACE_GAP = 280;

function linkMembers(nodes: readonly CanvasNode[]) {
  return nodes.flatMap((node) =>
    isChannelNode(node)
      ? [
          {
            id: node.id,
            parentId: node.parentId,
            position: node.position,
            nodeType: node.data.nodeType,
          },
        ]
      : [],
  );
}

function portPlacePosition(nodes: readonly CanvasNode[], id: string) {
  const at = absolutePosition(linkMembers(nodes), id);
  if (!at) return null;
  return { x: at.x + PORT_PLACE_GAP, y: at.y };
}

function edgePlacePosition(nodes: readonly CanvasNode[], sourceId: string, targetId: string) {
  const members = linkMembers(nodes);
  const sourceAt = absolutePosition(members, sourceId);
  const targetAt = absolutePosition(members, targetId);
  if (!sourceAt || !targetAt) return null;
  return { x: (sourceAt.x + targetAt.x) / 2, y: (sourceAt.y + targetAt.y) / 2 };
}

function noteCanvasNode(note: FlowNoteShape, selected: boolean): NoteCanvasNode {
  return {
    id: note.id,
    type: "note",
    position: note.position,
    width: note.width,
    height: note.height,
    style: { width: note.width, height: note.height },
    data: { text: note.data.text },
    selected,
    zIndex: 0,
    connectable: false,
  };
}

function flowNoteOf(node: NoteCanvasNode): FlowNoteShape {
  return {
    id: node.id,
    position: { x: node.position.x, y: node.position.y },
    width: node.width,
    height: node.height,
    data: { text: node.data.text },
  };
}

function presentNodes(nodes: CanvasNode[], members: readonly LinkMember[]): CanvasNode[] {
  return parentsFirst(nodes).map((node) => {
    if (!isChannelNode(node) || !isContainerNode(node.data.nodeType)) return node;
    const box = frameBox(node.id, members);
    return {
      ...node,
      style: { ...node.style, width: box.width, height: box.height },
    };
  });
}

function settleNote(node: NoteCanvasNode): NoteCanvasNode {
  return {
    ...node,
    zIndex: 0,
    connectable: false,
    style: { ...node.style, width: node.width, height: node.height },
  };
}

type CanvasSnapshot = {
  nodes: CanvasNode[];
  edges: Edge[];
};

type ProblemHighlight = {
  nodeId: string | null;
  edgeId: string | null;
  key: string;
};

type PickerPlace =
  | { mode: "open" }
  | { mode: "beside"; sourceId: string }
  | { mode: "point"; position: { x: number; y: number } }
  | {
      mode: "after-port";
      sourceId: string;
      sourceHandle: string;
      position: { x: number; y: number };
      besideSource: boolean;
    }
  | { mode: "insert-edge"; edgeId: string; position: { x: number; y: number } };

type PickerGhost = {
  position: { x: number; y: number };
  sourceId: string;
  sourceHandle: string;
};

type PickerState = {
  key: number;
  /** Toolbar and empty-canvas add toggle this picker shut and mark the button. */
  fromAdd: boolean;
  anchor: { x: number; y: number };
  preferAbove: boolean;
  place: PickerPlace;
  ghost: PickerGhost | null;
  returnFocusId: string | null;
};

export type PickerIntent =
  | { kind: "free" }
  | { kind: "afterPort"; sourceId: string; sourceHandle: string }
  | { kind: "insertOnEdge"; edgeId: string };

type CanvasMenuState =
  | { kind: "node"; nodeId: string; x: number; y: number }
  | { kind: "note"; nodeId: string; x: number; y: number }
  | { kind: "selection"; x: number; y: number }
  | { kind: "edge"; edgeId: string; x: number; y: number }
  | {
      kind: "pane";
      x: number;
      y: number;
      paste: "pending" | "ready" | "blocked";
      text: string;
    };

const SKIP_NOTE_MS = 4000;

const NODE_DRAG_THRESHOLD = 4;
const NUDGE_STEP = 8;
const NUDGE_SHIFT_STEP = 40;
const NUDGE_COALESCE_MS = 500;
/** How long an output add control stays after the pointer leaves the node. */
const PORT_ADD_HIDE_MS = 200;
const ARROW_DELTA: Record<string, { x: number; y: number }> = {
  ArrowUp: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 },
  ArrowLeft: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 },
};
const CANVAS_MIN_ZOOM = 0.25;
const CANVAS_MAX_ZOOM = 2;
const CHANNEL_EDGE_TYPE = "channel";
const CHANNEL_EDGE_MARKER = { type: MarkerType.ArrowClosed, color: "context-stroke" };
const nodeTypes = { channel: ChannelFlowNode, note: NoteFlowNode };
const edgeTypes = { [CHANNEL_EDGE_TYPE]: ChannelFlowEdge };
const PROBLEM_STROKE = "var(--refraq-tone-danger)";

function highlightTargets(problem: GraphProblem, active: ProblemHighlight): boolean {
  return active.nodeId
    ? problem.node_id === active.nodeId
    : problem.edge_id != null && problem.edge_id === active.edgeId;
}
const CanvasSurfaceContext = createContext<{
  editing: boolean;
  mutable: boolean;
  openNode: (nodeId: string) => void;
  openPickerAt: (screenPoint: { x: number; y: number }, intent: PickerIntent) => void;
  duplicateNode: (nodeId: string) => void;
  busyOutputs: ReadonlySet<string>;
  editingNoteId: string | null;
  draftNoteText: (noteId: string, text: string) => void;
  endNoteEdit: (noteId: string) => void;
}>({
  editing: false,
  mutable: false,
  openNode: () => {},
  openPickerAt: () => {},
  duplicateNode: () => {},
  busyOutputs: new Set<string>(),
  editingNoteId: null,
  draftNoteText: () => {},
  endNoteEdit: () => {},
});
const CanvasCatalogContext = createContext<readonly NodeTypeSpec[]>([]);
const CanvasRunContext = createContext<{
  phases: ReadonlyMap<string, string>;
  counts: ReadonlyMap<string, number>;
  onRun: (nodeId: string) => void;
}>({
  phases: new Map(),
  counts: new Map(),
  onRun: () => {},
});

const CanvasMotionContext = createContext<{
  entering: ReadonlySet<string>;
  drawing: ReadonlySet<string>;
}>({
  entering: new Set(),
  drawing: new Set(),
});

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function idsAdded(before: readonly { id: string }[], after: readonly { id: string }[]): string[] {
  const known = new Set(before.map((item) => item.id));
  return after.flatMap((item) => (known.has(item.id) ? [] : [item.id]));
}

type Props = {
  graph: Graph;
  catalog: NodeTypeSpec[];
  /** Edit page keeps authoring chrome. Browse hides it. */
  appearance: "edit" | "browse";
  /** Draft mutations are allowed. */
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
  /** Set on the editor canvas. */
  channelId?: string;
  /** Selects this node once when the canvas opens. */
  focusNodeId?: string | null;
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
  channelId,
  focusNodeId = null,
}: Props) {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const colorScheme = useComputedColorScheme("light", { getInitialValueInEffect: false });
  const { data: heldPermissions } = usePermissions<string[]>({});
  const { screenToFlowPosition, flowToScreenPosition, setCenter, getInternalNode, fitView } =
    useReactFlow();
  const store = useStoreApi();
  const triggerTypes = useMemo(
    () => new Set(catalog.filter((item) => item.trigger).map((item) => item.type)),
    [catalog],
  );
  const initial = useMemo(
    () => flowFromGraph(graph, triggerTypes),
    // The canvas owns edits after mount. The parent remounts only when a draft is loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const seededNodes: CanvasNode[] = [
    ...initial.notes.map((note) => noteCanvasNode(note, false)),
    ...initial.nodes.map((node) => ({ ...node, type: "channel" as const, zIndex: 1 })),
  ];
  const seededEdges = channelEdges(initial.edges);
  const [nodes, setNodes] = useState<CanvasNode[]>(seededNodes);
  const [edges, setEdges] = useState<Edge[]>(seededEdges);
  const [enteringIds, setEnteringIds] = useState<ReadonlySet<string>>(() => new Set());
  const [drawingIds, setDrawingIds] = useState<ReadonlySet<string>>(() => new Set());
  const [configNodeId, setConfigNodeId] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [picker, setPicker] = useState<PickerState | null>(null);
  const [highlight, setHighlight] = useState<ProblemHighlight | null>(null);
  const [problemsDismissed, setProblemsDismissed] = useState(0);
  const [connectNote, setConnectNote] = useState<{
    x: number;
    y: number;
    message?: "addRejected";
  } | null>(null);
  const [skipNote, setSkipNote] = useState("");
  const [contextMenu, setContextMenu] = useState<CanvasMenuState | null>(null);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const historyRef = useRef<History<CanvasSnapshot>>(
    createHistory(snapshotOf(seededNodes, seededEdges)),
  );
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const noteEditOrigin = useRef<{ id: string; text: string } | null>(null);
  const commitQueued = useRef(false);
  const flowRootRef = useRef<HTMLDivElement>(null);
  const closeTimerRef = useRef<number | null>(null);
  const closingRef = useRef(false);
  const focusReturnRef = useRef<string | null>(null);
  const cancelOverlayCloseRef = useRef<() => void>(() => {});
  const beginCloseRef = useRef<() => void>(() => {});
  const retainPickerRef = useRef(false);
  const pickerSeq = useRef(0);
  const skipTimer = useRef<number | null>(null);
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  const dragRef = useRef<DragPreview | null>(null);
  const [drag, setDrag] = useState<DragPreview | null>(null);
  const menuSeq = useRef(0);
  const highlightRef = useRef<ProblemHighlight | null>(highlight);
  nodesRef.current = nodes;
  edgesRef.current = edges;
  highlightRef.current = highlight;
  const frameMembers = useMemo(() => {
    const members = linkMembers(nodes);
    return drag ? reparentDrag(members, drag.ids, drag.frozen) : members;
  }, [nodes, drag]);
  const flowNodes = useMemo(() => presentNodes(nodes, frameMembers), [nodes, frameMembers]);
  const flowEdges = useMemo(
    () => (drag ? edgesAfterReparent(edges, frameMembers) : edges),
    [drag, edges, frameMembers],
  );
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

  const graphOf = (nextNodes: CanvasNode[], nextEdges: Edge[]) =>
    graphFromFlow(
      nextNodes.filter(isChannelNode).map((node) => ({
        id: node.id,
        position: node.position,
        data: node.data,
        ...(node.parentId ? { parentId: node.parentId } : {}),
      })),
      nextEdges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
      })),
      settingsRef.current,
      nextNodes.filter(isNoteNode).map(flowNoteOf),
    );

  const emit = (nextNodes: CanvasNode[], nextEdges: Edge[]) => {
    onChange(graphOf(nextNodes, nextEdges));
  };

  const graphNow = () => graphOf(nodesRef.current, edgesRef.current);

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

  const nudgeTimer = useRef<number | null>(null);

  const flushNudge = () => {
    if (nudgeTimer.current == null) return;
    window.clearTimeout(nudgeTimer.current);
    nudgeTimer.current = null;
    pushSnap();
  };

  const nudgeDirty = () =>
    !sameSnapshot(historyRef.current.present, snapshotOf(nodesRef.current, edgesRef.current));

  const scheduleNudgeCommit = () => {
    if (nudgeTimer.current != null) window.clearTimeout(nudgeTimer.current);
    nudgeTimer.current = window.setTimeout(() => {
      nudgeTimer.current = null;
      pushSnap();
    }, NUDGE_COALESCE_MS);
    // Undo during the burst flushes it first. Flags follow the uncommitted snap:
    // a burst that lands back on the current snapshot must not enable undo or hide redo.
    const dirty = nudgeDirty();
    setCanUndo(dirty || historyRef.current.past.length > 0);
    setCanRedo(!dirty && historyRef.current.future.length > 0);
  };

  const nudgeSelection = (dx: number, dy: number) => {
    if (!nodesRef.current.some((node) => node.selected)) return;
    const next = nodesRef.current.map((node) =>
      node.selected
        ? { ...node, position: { x: node.position.x + dx, y: node.position.y + dy } }
        : node,
    );
    nodesRef.current = next;
    setNodes(next);
    emit(next, edgesRef.current);
    scheduleNudgeCommit();
  };

  const restore = (snap: CanvasSnapshot) => {
    cancelOverlayCloseRef.current();
    const painted = paintProblems(snap.nodes, snap.edges);
    nodesRef.current = painted.nodes;
    edgesRef.current = painted.edges;
    setNodes(painted.nodes);
    setEdges(painted.edges);
    forgetMotion();
    setConfigNodeId(
      painted.nodes.find((node) => node.selected && isChannelNode(node))?.id ?? null,
    );
    emit(painted.nodes, painted.edges);
  };

  const undo = () => {
    flushNudge();
    flushCommit();
    const next = undoHistory(historyRef.current);
    if (next === historyRef.current) return;
    publishHistory(next);
    restore(next.present);
  };

  const redo = () => {
    // A dirty burst is an uncommitted edit. Flushing it would drop the redo stack
    // and then find nothing to redo. Leave both in place until the burst settles.
    if (nudgeTimer.current != null && nudgeDirty()) return;
    flushNudge();
    flushCommit();
    const next = redoHistory(historyRef.current);
    if (next === historyRef.current) return;
    publishHistory(next);
    restore(next.present);
  };

  const adoptedToken = useRef(adoptToken);
  useEffect(() => {
    if (adoptedToken.current === adoptToken) return;
    adoptedToken.current = adoptToken;
    const nextGraph = graph;
    if (JSON.stringify(graphNow()) === JSON.stringify(nextGraph)) return;
    cancelOverlayCloseRef.current();
    const selectedNodeIds = new Set(
      nodesRef.current.filter((node) => node.selected).map((node) => node.id),
    );
    const selectedEdgeIds = new Set(
      edgesRef.current.filter((edge) => edge.selected).map((edge) => edge.id),
    );
    const flow = flowFromGraph(nextGraph, triggerTypes);
    const adoptedNodes: CanvasNode[] = [
      ...flow.notes.map((note) => noteCanvasNode(note, selectedNodeIds.has(note.id))),
      ...flow.nodes.map((node) => ({
        ...node,
        type: "channel" as const,
        zIndex: 1,
        selected: selectedNodeIds.has(node.id),
      })),
    ];
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
    forgetMotion();
    setConfigNodeId((current) =>
      current != null && painted.nodes.some((node) => node.id === current) ? current : null,
    );
    // The stored graph is one undo step ahead of the pre-save canvas, so undo
    // returns to that unsaved graph.
    pushSnap();
  }, [adoptToken, triggerTypes, graph]);

  useEffect(() => {
    if (mutable) return;
    setPicker(null);
  }, [mutable]);

  useEffect(() => {
    if (mutable && appearance === "edit") return;
    setContextMenu((current) => (current?.kind === "edge" ? null : current));
  }, [mutable, appearance]);

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
      if (center) void setCenter(center.x, center.y, { duration: canvasViewportDuration() });
      return;
    }
    if (!active.edgeId) return;
    const edge = edgesRef.current.find((item) => item.id === active.edgeId);
    if (!edge) return;
    const source = centerOf(edge.source);
    const target = centerOf(edge.target);
    if (!source || !target) return;
    void setCenter((source.x + target.x) / 2, (source.y + target.y) / 2, {
      duration: canvasViewportDuration(),
    });
  };

  const focusProblem = (problem: GraphProblem) => {
    if (!problem.node_id && !problem.edge_id) return;
    cancelOverlayCloseRef.current();
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

  const focusedNode = useRef<string | null>(null);
  useEffect(() => {
    if (!focusNodeId || focusedNode.current === focusNodeId) return;
    if (!nodesRef.current.some((node) => node.id === focusNodeId)) return;
    focusedNode.current = focusNodeId;
    focusProblem({
      code: "focus",
      node_id: focusNodeId,
      edge_id: null,
      path: [],
      detail: "",
    });
  }, [focusNodeId]);

  const placeNode = (
    spec: NodeTypeSpec,
    position: { x: number; y: number },
    options?: {
      link?: { sourceId: string; sourceHandle: string };
      continueTo?: { targetId: string; targetHandle: string };
      removeEdgeId?: string;
    },
  ) => {
    if (!mutable || !canAuthorNodeType(spec.permission, heldPermissions)) return;
    cancelOverlayCloseRef.current();
    clearHighlight();
    const label = nodeTypeLabel(t, spec);
    const count = nodesRef.current.filter(
      (node) => isChannelNode(node) && node.data.nodeType === spec.type,
    ).length;
    const name = count === 0 ? label : `${label} ${count + 1}`;
    const priorEdges = edgesRef.current;
    const id = newGraphId("nd");
    const ref = nodeRef(
      spec.type,
      nodesRef.current.flatMap((node) => (isChannelNode(node) ? [node.data.ref] : [])),
    );
    const link = options?.link;
    const continueTo = options?.continueTo;
    const members = linkMembers(nodesRef.current);
    const rejectAdd = () => {
      const anchor = picker?.anchor;
      setPicker(null);
      if (!anchor) return;
      setConnectNote({ x: anchor.x + 12, y: anchor.y + 12, message: "addRejected" });
    };
    let placement: { parentId?: string; position: { x: number; y: number } };
    if (link && continueTo) {
      const onEdge = placementOnEdge(
        members,
        link.sourceId,
        continueTo.targetId,
        link.sourceHandle,
      );
      if (!onEdge) {
        rejectAdd();
        return;
      }
      placement = onEdge;
    } else if (link) {
      placement = placementFromPort(members, link.sourceId, link.sourceHandle, position);
    } else {
      placement = { position };
    }
    const created: ChannelNode = {
      id,
      type: "channel",
      position: placement.position,
      ...(placement.parentId ? { parentId: placement.parentId } : {}),
      zIndex: 1,
      selected: true,
      data: emptyNodeData(
        spec.type,
        ref,
        name,
        defaultConfig(spec.config_schema as SchemaObject),
        spec.trigger,
      ),
    };
    const nextNodes = [...nodesRef.current.map((node) => ({ ...node, selected: false })), created];
    let nextEdges: Edge[] = edgesRef.current
      .filter((edge) => edge.id !== options?.removeEdgeId)
      .map((edge) => ({ ...edge, selected: false }));
    const draftOf = (edgesNow: Edge[]) => graphOf(nextNodes, edgesNow);
    const accepts = (connection: Connection) =>
      connectionAllowed(draftOf(nextEdges), catalog, connection) &&
      frameLinkAllowed(linkMembers(nextNodes), connection);
    if (link) {
      const input = spec.inputs.find((port) => {
        const connection = {
          source: link.sourceId,
          target: id,
          sourceHandle: link.sourceHandle,
          targetHandle: port.port,
        };
        return accepts(connection);
      });
      if (!input) {
        rejectAdd();
        return;
      }
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
    if (continueTo) {
      const output = spec.outputs.find((port) =>
        accepts({
          source: id,
          target: continueTo.targetId,
          sourceHandle: port.port,
          targetHandle: continueTo.targetHandle,
        }),
      );
      if (!output) {
        rejectAdd();
        return;
      }
      nextEdges = channelEdges(
        addEdge(
          {
            source: id,
            target: continueTo.targetId,
            sourceHandle: output.port,
            targetHandle: continueTo.targetHandle,
          },
          nextEdges,
          { getEdgeId: () => newGraphId("ed") },
        ),
      );
    }
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    rememberEntering([id]);
    rememberDrawing(idsAdded(priorEdges, nextEdges), nextEdges);
    setConfigNodeId(null);
    setPicker(null);
    emit(nextNodes, nextEdges);
    commitNow();
    const origin = placement.parentId ? absolutePosition(members, placement.parentId) : null;
    ensureVisible(
      origin
        ? { x: origin.x + placement.position.x, y: origin.y + placement.position.y }
        : placement.position,
    );
  };

  const ensureVisible = (position: { x: number; y: number }) => {
    const pane = flowRootRef.current?.querySelector(".react-flow");
    if (!(pane instanceof HTMLElement)) return;
    const rect = pane.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return;
    const topLeft = flowToScreenPosition(position);
    const bottomRight = flowToScreenPosition({ x: position.x + 208, y: position.y + 56 });
    const inside =
      topLeft.x >= rect.left &&
      topLeft.y >= rect.top &&
      bottomRight.x <= rect.right &&
      bottomRight.y <= rect.bottom;
    if (inside) return;
    void setCenter(position.x + 104, position.y + 28, { duration: canvasViewportDuration() });
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

  const stagePoint = (screen: { x: number; y: number }) => {
    const stage = flowRootRef.current?.getBoundingClientRect();
    if (!stage) return screen;
    return { x: screen.x - stage.left, y: screen.y - stage.top };
  };

  const focusedNodeId = () => {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return null;
    const node = active.closest(".react-flow__node");
    return node instanceof HTMLElement ? node.getAttribute("data-id") : null;
  };

  const showPicker = (next: Omit<PickerState, "key">) => {
    if (!mutable || appearance !== "edit") return;
    retainPickerRef.current = true;
    queueMicrotask(() => {
      retainPickerRef.current = false;
    });
    pickerSeq.current += 1;
    cancelOverlayCloseRef.current();
    setConfigNodeId(null);
    setConnectNote(null);
    setPicker({ ...next, key: pickerSeq.current });
  };

  const firstOutputHandle = (sourceId: string, spec: NodeTypeSpec): string | null => {
    const source = nodesRef.current.find((node) => node.id === sourceId);
    if (!source || !isChannelNode(source)) return null;
    const sourceSpec = catalog.find((item) => item.type === source.data.nodeType);
    const outputs = sourceSpec?.outputs ?? [];
    const graph = graphNow();
    for (const output of outputs) {
      const targets = outputTargetTypes(graph, catalog, sourceId, output.port);
      if (targets.some((item) => item.type === spec.type)) return output.port;
    }
    return null;
  };

  /** Named entry for a later canvas menu. Toolbar, Tab, and a dragged wire use their own openers. */
  function openPickerAt(screenPoint: { x: number; y: number }, intent: PickerIntent) {
    const anchor = stagePoint(screenPoint);
    if (intent.kind === "free") {
      showPicker({
        fromAdd: false,
        anchor,
        preferAbove: false,
        place: { mode: "point", position: screenToFlowPosition(screenPoint) },
        ghost: null,
        returnFocusId: focusedNodeId(),
      });
      return;
    }
    if (intent.kind === "afterPort") {
      const position = portPlacePosition(nodesRef.current, intent.sourceId);
      if (!position) return;
      showPicker({
        fromAdd: false,
        anchor,
        preferAbove: false,
        place: {
          mode: "after-port",
          sourceId: intent.sourceId,
          sourceHandle: intent.sourceHandle,
          position,
          besideSource: true,
        },
        ghost: null,
        returnFocusId: intent.sourceId,
      });
      return;
    }
    const edge = edgesRef.current.find((item) => item.id === intent.edgeId);
    if (!edge) return;
    const position =
      edgePlacePosition(nodesRef.current, edge.source, edge.target) ??
      screenToFlowPosition(screenPoint);
    showPicker({
      fromAdd: false,
      anchor,
      preferAbove: false,
      place: { mode: "insert-edge", edgeId: edge.id, position },
      ghost: null,
      returnFocusId: focusedNodeId(),
    });
  }

  const openAddPicker = (screen: { x: number; y: number }, preferAbove: boolean) => {
    if (!mutable || appearance !== "edit") return;
    if (picker?.fromAdd) {
      beginCloseRef.current();
      return;
    }
    const selected = nodesRef.current.filter((node) => node.selected && isChannelNode(node));
    const place: PickerPlace =
      selected.length === 1 && selected[0]
        ? { mode: "beside", sourceId: selected[0].id }
        : { mode: "open" };
    showPicker({
      fromAdd: true,
      anchor: stagePoint(screen),
      preferAbove,
      place,
      ghost: null,
      returnFocusId: selected.length === 1 ? selected[0]!.id : focusedNodeId(),
    });
  };

  const openToolbarPicker = () => {
    const button = flowRootRef.current?.querySelector(".channel-canvas-toolbar__add");
    if (!(button instanceof HTMLElement)) return;
    const rect = button.getBoundingClientRect();
    openAddPicker({ x: rect.left, y: rect.top }, true);
  };

  const onNodesChange = (changes: NodeChange<CanvasNode>[]) => {
    const next = applyNodeChanges(changes, nodesRef.current).map((node) =>
      isNoteNode(node) ? settleNote(node) : node,
    );
    nodesRef.current = next;
    setNodes(next);
    const selected = next.find((node) => node.selected);
    setConfigNodeId((current) => {
      if (current == null) return null;
      const open = next.find((node) => node.id === current);
      if (!open) return null;
      // Pane click starts the leave, then React Flow deselects. Keep the overlay
      // mounted until that leave finishes. A removed node still closes now.
      if (closingRef.current) return current;
      return open.selected ? current : null;
    });
    const marked = highlightRef.current;
    if (marked && selected && selected.id !== marked.nodeId) clearHighlight();
    if (selected && !retainPickerRef.current) setPicker(null);
    if (
      !store.getState().multiSelectionActive &&
      selected &&
      edgesRef.current.some((edge) => edge.selected)
    ) {
      const cleared = edgesRef.current.map((edge) => ({ ...edge, selected: false }));
      edgesRef.current = cleared;
      setEdges(cleared);
    }
    if (noteEditOrigin.current && !next.some((node) => node.id === noteEditOrigin.current?.id)) {
      noteEditOrigin.current = null;
      setEditingNoteId(null);
    }
    const noteResizing = changes.some(
      (change) =>
        change.type === "dimensions" &&
        change.resizing === true &&
        next.some((node) => node.id === change.id && isNoteNode(node)),
    );
    const noteResizeEnded = changes.some(
      (change) =>
        change.type === "dimensions" &&
        change.resizing === false &&
        next.some((node) => node.id === change.id && isNoteNode(node)),
    );
    if (shouldCommitNodeChanges(changes) || noteResizeEnded) {
      emit(next, edgesRef.current);
      scheduleCommit();
    } else if (changes.some((change) => change.type === "position") || noteResizing) {
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
    if (selected && !store.getState().multiSelectionActive) {
      focusReturnRef.current = null;
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

  const onNodeDragStart = (
    _event: MouseEvent | TouchEvent,
    _node: CanvasNode,
    dragged: CanvasNode[],
  ) => {
    const ids = dragged.flatMap((node) => (isChannelNode(node) ? [node.id] : []));
    if (ids.length === 0) return;
    const gesture = { ids, frozen: freezeFrames(linkMembers(nodesRef.current)) };
    dragRef.current = gesture;
    setDrag(gesture);
  };

  const onNodeDragStop = (
    _event: MouseEvent | TouchEvent,
    _node: CanvasNode,
    _dragged: CanvasNode[],
  ) => {
    const gesture = dragRef.current;
    dragRef.current = null;
    if (!gesture) {
      setDrag(null);
      return;
    }
    const dropped = reparentDrag(linkMembers(nodesRef.current), gesture.ids, gesture.frozen);
    const byId = new Map(dropped.map((member) => [member.id, member]));
    const nextNodes = nodesRef.current.map((node) => {
      if (!isChannelNode(node)) return node;
      const next = byId.get(node.id);
      if (!next) return node;
      const sameParent = (node.parentId ?? undefined) === next.parentId;
      const samePosition = node.position.x === next.position.x && node.position.y === next.position.y;
      if (sameParent && samePosition) return node;
      const { parentId: _previous, ...rest } = node;
      return next.parentId
        ? { ...rest, parentId: next.parentId, position: { ...next.position } }
        : { ...rest, position: { ...next.position } };
    });
    const nextEdges = edgesAfterReparent(edgesRef.current, dropped);
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setDrag(null);
    setNodes(nextNodes);
    setEdges(nextEdges);
    emit(nextNodes, nextEdges);
    commitNow();
  };

  const onConnect = (connection: Connection) => {
    if (!connectionAllowed(graphNow(), catalog, connection)) return;
    if (!frameLinkAllowed(linkMembers(nodesRef.current), connection)) return;
    const priorEdges = edgesRef.current;
    const next = channelEdges(
      addEdge(connection, edgesRef.current, { getEdgeId: () => newGraphId("ed") }),
    );
    if (next === edgesRef.current) return;
    edgesRef.current = next;
    setEdges(next);
    rememberDrawing(idsAdded(priorEdges, next), next);
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
    const anchor = stagePoint(point);
    if (specs.length === 0) {
      setConnectNote({ x: anchor.x + 12, y: anchor.y + 12 });
      return;
    }
    setConnectNote(null);
    releaseSelection();
    const position = screenToFlowPosition(point);
    showPicker({
      fromAdd: false,
      anchor,
      preferAbove: false,
      place: {
        mode: "after-port",
        sourceId: connectionState.fromNode.id,
        sourceHandle,
        position,
        besideSource: false,
      },
      ghost: { position, sourceId: connectionState.fromNode.id, sourceHandle },
      returnFocusId: connectionState.fromNode.id,
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

  const restoreNodeFocus = (nodeId: string | null) => {
    if (!nodeId) return;
    const node = flowRootRef.current?.querySelector(
      `.react-flow__node[data-id="${CSS.escape(nodeId)}"]`,
    );
    if (node instanceof HTMLElement) node.focus();
  };

  const cancelOverlayClose = () => {
    if (closeTimerRef.current != null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    closingRef.current = false;
    focusReturnRef.current = null;
    setLeaving(false);
  };
  cancelOverlayCloseRef.current = cancelOverlayClose;

  const finishOverlayClose = (nodeId: string | null, pickerAtClose: PickerState | null) => {
    closeTimerRef.current = null;
    closingRef.current = false;
    setLeaving(false);
    if (nodeId != null && nodesRef.current.some((node) => node.id === nodeId && node.selected)) {
      const nextNodes = nodesRef.current.map((node) =>
        node.id === nodeId ? { ...node, selected: false } : node,
      );
      nodesRef.current = nextNodes;
      setNodes(nextNodes);
    }
    setConfigNodeId((current) => (current === nodeId ? null : current));
    setPicker((current) => (current === pickerAtClose ? null : current));
  };

  const beginClose = () => {
    if (picker != null && configNodeId == null) {
      const returnId = picker.returnFocusId;
      setPicker(null);
      setConnectNote(null);
      restoreNodeFocus(returnId);
      return;
    }
    const overlayOpen = configNodeId != null || picker != null;
    if (!overlayOpen) {
      clearSelection();
      return;
    }
    if (closingRef.current) return;
    const nodeId = configNodeId;
    const pickerAtClose = picker;
    focusReturnRef.current = nodeId;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      clearSelection();
      return;
    }
    closingRef.current = true;
    clearHighlight();
    setProblemsDismissed((count) => count + 1);
    setLeaving(true);
    closeTimerRef.current = window.setTimeout(() => {
      finishOverlayClose(nodeId, pickerAtClose);
    }, MOTION_MS.base);
  };
  beginCloseRef.current = beginClose;

  const selected =
    nodes.find((node): node is ChannelNode => node.id === configNodeId && isChannelNode(node)) ??
    null;
  const selectedSpec = catalog.find((item) => item.type === selected?.data.nodeType);
  const overlayRef = useRef<HTMLDivElement>(null);
  const labelGraph = problemGraphOf(nodes, edges);
  const revealKey =
    selected != null && highlight?.nodeId === selected.id ? highlight.key : null;
  const outputSchemas = new Map<string, SchemaObject | null>();
  for (const port of ports) {
    if (port.direction !== "output") continue;
    outputSchemas.set(`${port.node_id}:${port.port}`, port.schema);
    if (port.port === "main") outputSchemas.set(port.node_id, port.schema);
  }
  const summaryKey = sessionRun ? recordedKey(sessionRun) : "";
  const [latestExecutions, setLatestExecutions] = useState<NodeExecution[]>([]);
  useEffect(() => {
    if (!sessionRun || !channelId) {
      setLatestExecutions([]);
      return;
    }
    const queries = sessionRun.node_summaries.flatMap((summary) => {
      const query = latestExecutionQuery(summary);
      return query ? [query] : [];
    });
    if (queries.length === 0) {
      setLatestExecutions([]);
      return;
    }
    let cancelled = false;
    void Promise.allSettled(
      queries.map((query) => listExecutions(channelId, sessionRun.run.job_id, query)),
    ).then((results) => {
      if (cancelled) return;
      setLatestExecutions(
        results.flatMap((result) => (result.status === "fulfilled" ? result.value.items : [])),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [sessionRun, channelId, summaryKey]);
  const latestStatus = useMemo(() => {
    const statuses = new Map<string, string>();
    for (const item of latestExecutions) statuses.set(item.node_id, item.status);
    return statuses;
  }, [latestExecutions]);
  const phases = useMemo(
    () => (sessionRun ? phaseByNode(sessionRun, sessionRun.graph ?? graph, latestStatus) : new Map()),
    [sessionRun, graph, latestStatus],
  );
  useEffect(() => {
    setDrawingIds((current) => {
      if (current.size === 0) return current;
      let changed = false;
      const next = new Set(current);
      for (const id of current) {
        const edge = edgesRef.current.find((item) => item.id === id);
        if (edge && phases.get(edge.target) === "running") {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [phases]);
  useEffect(() => {
    const root = flowRootRef.current;
    if (!root) return;
    const onEnd = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const name = "animationName" in event ? String(event.animationName) : "";
      if (name === "channel-flow-node-enter") {
        const id = target.closest(".react-flow__node")?.getAttribute("data-id");
        if (id) releaseEntering(id);
        return;
      }
      if (name === "channel-flow-edge-draw") {
        const id = target.closest(".react-flow__edge")?.getAttribute("data-id");
        if (id) releaseDrawing(id);
      }
    };
    root.addEventListener("animationend", onEnd);
    return () => root.removeEventListener("animationend", onEnd);
  });
  const counts = useMemo(
    () =>
      sessionRun
        ? executionCountByNode(sessionRun.node_summaries)
        : new Map<string, number>(),
    [sessionRun],
  );
  const [pinnedRounds, setPinnedRounds] = useState<Record<string, number>>({});
  const [adoptedRounds, setAdoptedRounds] = useState<Record<string, number>>({});
  const [roundTotals, setRoundTotals] = useState<Record<string, number>>({});
  const resolvedScope = useRef<NodeSampleScopeLevel[]>([]);
  const sampleScope = useMemo(
    () =>
      selected
        ? scopeRequest(graph.nodes, selected.id, pinnedRounds, resolvedScope.current)
        : undefined,
    [graph.nodes, pinnedRounds, selected],
  );
  const sampleState = useNodeSample({
    channelId: channelId ?? "",
    jobId: sessionRun?.run.job_id ?? null,
    nodeId: selected?.id ?? null,
    graph,
    scope: sampleScope,
    recordedKey: summaryKey,
    enabled: Boolean(channelId && sessionRun && selected),
  });
  useEffect(() => {
    const next = sampleState.sample;
    if (!next) return;
    resolvedScope.current = next.scope;
    setAdoptedRounds((current) => {
      let changed = false;
      const adopted = { ...current };
      for (const level of next.scope) {
        if (pinnedRounds[level.container_node_id] != null) continue;
        if (adopted[level.container_node_id] !== level.round) {
          adopted[level.container_node_id] = level.round;
          changed = true;
        }
      }
      return changed ? adopted : current;
    });
    setRoundTotals((current) => {
      let changed = false;
      const totals = { ...current };
      for (const level of next.scope) {
        if (totals[level.container_node_id] == null) {
          totals[level.container_node_id] = level.rounds_total;
          changed = true;
        }
      }
      return changed ? totals : current;
    });
  }, [pinnedRounds, sampleState.sample]);
  const roundOf = useCallback(
    (containerId: string) =>
      pinnedRounds[containerId] ??
      adoptedRounds[containerId] ??
      sampleState.sample?.scope.find((level) => level.container_node_id === containerId)?.round ??
      0,
    [adoptedRounds, pinnedRounds, sampleState.sample],
  );
  const totalOf = useCallback(
    (containerId: string) =>
      roundTotals[containerId] ??
      sampleState.sample?.scope.find((level) => level.container_node_id === containerId)
        ?.rounds_total ??
      0,
    [roundTotals, sampleState.sample],
  );
  const setRound = useCallback((containerId: string, round: number) => {
    setPinnedRounds((current) =>
      current[containerId] === round ? current : { ...current, [containerId]: round },
    );
  }, []);
  const rememberRounds = useCallback((containerId: string, total: number) => {
    setRoundTotals((current) =>
      current[containerId] === total ? current : { ...current, [containerId]: total },
    );
  }, []);
  const caretRef = useRef<TemplateCaret | null>(null);
  const [insertReady, setInsertReady] = useState(false);
  const onTemplateCaret = useCallback((caret: TemplateCaret | null) => {
    caretRef.current = caret;
    setInsertReady(caret != null);
  }, []);
  const onInsert = useCallback((ref: string, path: PathSegment[]) => {
    const caret = caretRef.current;
    if (!caret) return;
    const place = caret.read();
    caret.write(place.from, place.to, templateInsertion(place.text, place.head, outputPath(ref, path)));
  }, []);
  const completion = useMemo(
    () => completionSamples(sampleState.sample?.upstream ?? []),
    [sampleState.sample],
  );
  const runNodes: RunNodeInfo[] = nodes.flatMap((node) =>
    isChannelNode(node)
      ? [
          {
            id: node.id,
            name: node.data.name,
            ref: node.data.ref,
            type: node.data.nodeType,
            parent: node.parentId,
          },
        ]
      : [],
  );
  const overlayKey = selected?.id ?? null;
  const pickerKey = picker?.key ?? null;
  useEffect(() => {
    if (overlayKey == null || leaving) return;
    overlayRef.current?.focus();
  }, [overlayKey, leaving]);
  useEffect(() => {
    if (overlayKey != null || leaving || pickerKey != null) return;
    const nodeId = focusReturnRef.current;
    if (!nodeId) return;
    focusReturnRef.current = null;
    restoreNodeFocus(nodeId);
  }, [overlayKey, leaving, pickerKey]);
  useEffect(() => {
    if ((overlayKey == null && pickerKey == null) || leaving) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      beginCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [overlayKey, pickerKey, leaving]);
  useEffect(() => {
    if (contextMenu == null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      event.preventDefault();
      event.stopPropagation();
      menuSeq.current += 1;
      setContextMenu(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [contextMenu]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      if (!canvasShortcutTarget(event.target)) return;
      if (configNodeId != null || picker != null || leaving) return;
      clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [configNodeId, picker, leaving]);
  useEffect(
    () => () => {
      if (closeTimerRef.current != null) window.clearTimeout(closeTimerRef.current);
      if (nudgeTimer.current != null) window.clearTimeout(nudgeTimer.current);
    },
    [],
  );
  const hasTrigger = nodes.some((node) => isChannelNode(node) && node.data.trigger);
  const pickerTypes = (): NodeTypeSpec[] => {
    if (!picker) return [];
    const visible = catalog.filter((item) => !hasTrigger || !item.trigger);
    const place = picker.place;
    if (place.mode === "after-port") {
      const reachable = new Set(
        outputTargetTypes(graphNow(), catalog, place.sourceId, place.sourceHandle).map(
          (item) => item.type,
        ),
      );
      return visible.filter((item) => reachable.has(item.type));
    }
    if (place.mode === "insert-edge") {
      const edge = edges.find((item) => item.id === place.edgeId);
      if (!edge) return [];
      const reachable = new Set(
        insertableTypes(graphNow(), catalog, {
          source: { node_id: edge.source, port: edge.sourceHandle || "main" },
          target: { node_id: edge.target, port: edge.targetHandle || "main" },
        }).map((item) => item.type),
      );
      return visible.filter((item) => reachable.has(item.type));
    }
    if (place.mode === "beside") {
      const linked = visible.filter((item) => firstOutputHandle(place.sourceId, item) != null);
      return linked.length > 0 ? linked : visible;
    }
    return visible;
  };
  const pickerEntries: PickerEntry[] = pickerTypes().map((item) => {
    const allowed = canAuthorNodeType(item.permission, heldPermissions);
    const reason =
      !allowed && item.permission
        ? t("channels.canvas.permissionRequired", { permission: item.permission })
        : "";
    return { spec: item, disabled: !allowed, reason };
  });

  const chooseSpec = (spec: NodeTypeSpec) => {
    if (!picker) return;
    const place = picker.place;
    if (place.mode === "after-port") {
      const beside = place.besideSource
        ? portPlacePosition(nodesRef.current, place.sourceId)
        : null;
      const position = beside ?? place.position;
      placeNode(spec, position, {
        link: { sourceId: place.sourceId, sourceHandle: place.sourceHandle },
      });
      return;
    }
    if (place.mode === "insert-edge") {
      const edge = edgesRef.current.find((item) => item.id === place.edgeId);
      if (!edge) return;
      placeNode(spec, place.position, {
        removeEdgeId: edge.id,
        link: { sourceId: edge.source, sourceHandle: edge.sourceHandle || "main" },
        continueTo: { targetId: edge.target, targetHandle: edge.targetHandle || "main" },
      });
      return;
    }
    if (place.mode === "beside") {
      const handle = firstOutputHandle(place.sourceId, spec);
      const position = portPlacePosition(nodesRef.current, place.sourceId) ?? openPosition();
      placeNode(
        spec,
        position,
        handle ? { link: { sourceId: place.sourceId, sourceHandle: handle } } : undefined,
      );
      return;
    }
    if (place.mode === "point") {
      placeNode(spec, place.position);
      return;
    }
    placeNode(spec, openPosition());
  };

  const selectAll = () => {
    const nextNodes = nodesRef.current.map((node) => ({ ...node, selected: true }));
    const nextEdges = edgesRef.current.map((edge) => ({ ...edge, selected: true }));
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    if (nextNodes.length !== 1) setConfigNodeId(null);
  };

  const selectedNodeIds = () =>
    nodesRef.current.filter((node) => node.selected).map((node) => node.id);

  const showSkip = (skipped: PasteSkip) => {
    const parts: string[] = [];
    if (skipped.trigger > 0) {
      parts.push(t("channels.canvas.skipTrigger", { count: skipped.trigger }));
    }
    if (skipped.permission > 0) {
      parts.push(
        t("channels.canvas.skipPermission", {
          count: skipped.permission,
          permission: skipped.permissions.join(", "),
        }),
      );
    }
    if (skipped.unknown > 0) {
      parts.push(t("channels.canvas.skipUnknown", { count: skipped.unknown }));
    }
    if (parts.length === 0) return;
    if (skipTimer.current != null) window.clearTimeout(skipTimer.current);
    setSkipNote(parts.join(" "));
    skipTimer.current = window.setTimeout(() => {
      skipTimer.current = null;
      setSkipNote("");
    }, SKIP_NOTE_MS);
  };

  useEffect(
    () => () => {
      if (skipTimer.current != null) window.clearTimeout(skipTimer.current);
    },
    [],
  );

  const applyAdded = (result: ReturnType<typeof pasteFragment>) => {
    showSkip(result.skipped);
    if (result.nodes.length === 0 && result.notes.length === 0) return;
    const priorNodes = nodesRef.current;
    const priorEdges = edgesRef.current;
    const flow = flowFromGraph(
      {
        nodes: result.nodes,
        edges: result.edges,
        settings: settingsRef.current,
        notes: result.notes,
      },
      triggerTypes,
    );
    const nextNodes: CanvasNode[] = [
      ...nodesRef.current.map((node) => ({ ...node, selected: false })),
      ...flow.nodes.map((node) => ({
        ...node,
        type: "channel" as const,
        zIndex: 1,
        selected: true,
      })),
      ...flow.notes.map((note) => noteCanvasNode(note, true)),
    ];
    const nextEdges = channelEdges([
      ...edgesRef.current.map((edge) => ({ ...edge, selected: false })),
      ...flow.edges.map((edge) => ({ ...edge, selected: true })),
    ]);
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    rememberEntering(idsAdded(priorNodes, nextNodes));
    rememberDrawing(idsAdded(priorEdges, nextEdges), nextEdges);
    setConfigNodeId(null);
    setPicker(null);
    emit(nextNodes, nextEdges);
    commitNow();
  };

  const duplicateIds = (ids: readonly string[]) => {
    if (!mutable || appearance !== "edit" || ids.length === 0) return;
    const fragment = serializeFragment(graphNow(), ids);
    applyAdded(pasteFragment(fragment, graphNow(), catalog, heldPermissions, null));
  };

  const writeFragment = async (ids: readonly string[]) => {
    if (ids.length === 0) return false;
    const text = JSON.stringify(serializeFragment(graphNow(), ids));
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      presentConsoleNotification({
        type: "error",
        title: t("channels.canvas.clipboardFailed"),
      });
      return false;
    }
  };

  const removeNodes = (ids: readonly string[]) => {
    const drop = new Set(ids);
    if (!nodesRef.current.some((node) => drop.has(node.id))) return;
    const nextNodes = nodesRef.current.filter((node) => !drop.has(node.id));
    const nextEdges = edgesRef.current.filter(
      (edge) => !drop.has(edge.source) && !drop.has(edge.target),
    );
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    setConfigNodeId((current) => (current != null && drop.has(current) ? null : current));
    emit(nextNodes, nextEdges);
    commitNow();
  };

  const removeEdge = (edgeId: string) => {
    if (!edgesRef.current.some((edge) => edge.id === edgeId)) return;
    const nextEdges = edgesRef.current.filter((edge) => edge.id !== edgeId);
    edgesRef.current = nextEdges;
    setEdges(nextEdges);
    emit(nodesRef.current, nextEdges);
    commitNow();
  };

  const pasteText = (text: string) => {
    if (!mutable || appearance !== "edit") return;
    const fragment = parseFragment(text);
    if (!fragment) return;
    const point = pointerRef.current;
    applyAdded(
      pasteFragment(
        fragment,
        graphNow(),
        catalog,
        heldPermissions,
        point ? screenToFlowPosition(point) : null,
      ),
    );
  };

  const viewportCenter = () => {
    const pane = flowRootRef.current?.querySelector(".react-flow");
    const rect = pane instanceof HTMLElement ? pane.getBoundingClientRect() : null;
    if (!rect || rect.width < 8 || rect.height < 8) return { x: 160, y: 120 };
    return screenToFlowPosition({
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    });
  };

  const addNote = (position: { x: number; y: number }) => {
    if (!mutable || appearance !== "edit") return;
    cancelOverlayCloseRef.current();
    clearHighlight();
    const created = noteCanvasNode(
      {
        id: newGraphId("nt"),
        position,
        width: NOTE_WIDTH,
        height: NOTE_HEIGHT,
        data: { text: "" },
      },
      true,
    );
    const nextNodes: CanvasNode[] = [
      ...nodesRef.current.map((node) => ({ ...node, selected: false })),
      created,
    ];
    const nextEdges = edgesRef.current.map((edge) => ({ ...edge, selected: false }));
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    rememberEntering([created.id]);
    setConfigNodeId(null);
    setPicker(null);
    noteEditOrigin.current = { id: created.id, text: "" };
    setEditingNoteId(created.id);
    emit(nextNodes, nextEdges);
    commitNow();
  };

  const draftNoteText = (noteId: string, text: string) => {
    const next = nodesRef.current.map((node) =>
      isNoteNode(node) && node.id === noteId ? { ...node, data: { text } } : node,
    );
    nodesRef.current = next;
    setNodes(next);
  };

  const endNoteEdit = (noteId: string) => {
    const origin = noteEditOrigin.current;
    if (origin?.id === noteId) noteEditOrigin.current = null;
    setEditingNoteId((current) => (current === noteId ? null : current));
    const node = nodesRef.current.find((item) => item.id === noteId);
    if (!node || !origin || origin.id !== noteId || !isNoteNode(node) || node.data.text === origin.text) {
      return;
    }
    emit(nodesRef.current, edgesRef.current);
    commitNow();
  };

  const selectOnly = (nodeId: string) => {
    const nextNodes = nodesRef.current.map((node) => ({ ...node, selected: node.id === nodeId }));
    const nextEdges = edgesRef.current.map((edge) => ({ ...edge, selected: false }));
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
  };

  const openNodeMenu = (nodeId: string, x: number, y: number) => {
    const selected = nodesRef.current.filter((node) => node.selected);
    const already = selected.some((node) => node.id === nodeId);
    if (already && selected.length > 1) {
      setContextMenu({ kind: "selection", x, y });
      return;
    }
    if (!already) selectOnly(nodeId);
    const target = nodesRef.current.find((node) => node.id === nodeId);
    setContextMenu(
      target && isNoteNode(target)
        ? { kind: "note", nodeId, x, y }
        : { kind: "node", nodeId, x, y },
    );
  };

  const openPaneMenu = (x: number, y: number) => {
    const seq = menuSeq.current + 1;
    menuSeq.current = seq;
    const canPaste = mutable && appearance === "edit";
    setContextMenu({ kind: "pane", x, y, paste: "pending", text: "" });
    if (!canPaste) return;
    const read = navigator.clipboard?.readText?.bind(navigator.clipboard);
    if (!read) {
      setContextMenu({ kind: "pane", x, y, paste: "blocked", text: "" });
      return;
    }
    void read().then(
      (text) => {
        if (menuSeq.current !== seq) return;
        setContextMenu((current) =>
          current?.kind === "pane" ? { ...current, paste: "ready", text } : current,
        );
      },
      () => {
        if (menuSeq.current !== seq) return;
        setContextMenu((current) =>
          current?.kind === "pane" ? { ...current, paste: "blocked", text: "" } : current,
        );
      },
    );
  };

  const closeMenu = () => {
    menuSeq.current += 1;
    setContextMenu(null);
  };

  const openNodeConfig = (nodeId: string) => {
    cancelOverlayClose();
    setConfigNodeId(nodeId);
    setPicker(null);
    const marked = highlightRef.current;
    if (marked && marked.nodeId !== nodeId) clearHighlight();
  };

  const onCanvasKeyDownCapture = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const delta = ARROW_DELTA[event.key];
    if (!delta) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!canvasShortcutTarget(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    if (!mutable) return;
    const step = event.shiftKey ? NUDGE_SHIFT_STEP : NUDGE_STEP;
    nudgeSelection(delta.x * step, delta.y * step);
  };

  const onCanvasKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter") return;
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.classList.contains("react-flow__node")) return;
    const nodeId = target.getAttribute("data-id");
    if (!nodeId) return;
    const focused = nodesRef.current.find((node) => node.id === nodeId);
    if (!focused || isNoteNode(focused)) return;
    if (nodesRef.current.filter((node) => node.selected).length > 1) return;
    openNodeConfig(nodeId);
  };

  const selectedNodes = nodes.filter((node) => node.selected);
  const adjacentTo = selectedNodes.length === 1 ? selectedNodes[0]!.id : null;
  const busyOutputs = new Set(
    edges.map((edge) => `${edge.source}:${edge.sourceHandle || "main"}`),
  );
  const stageRect = flowRootRef.current?.getBoundingClientRect();
  const pickerFrame = { width: stageRect?.width ?? 0, height: stageRect?.height ?? 0 };

  return (
    <Stack gap={0} flex={1} mih={0} h="100%" w="100%" pos="relative">
        <CanvasSurfaceContext.Provider
          value={{
            editing: appearance === "edit",
            mutable,
            openNode: openNodeConfig,
            openPickerAt,
            duplicateNode: (nodeId) => duplicateIds([nodeId]),
            busyOutputs,
            editingNoteId,
            draftNoteText,
            endNoteEdit,
          }}
        >
        <CanvasCatalogContext.Provider value={catalog}>
        <CanvasRunContext.Provider
          value={{ phases, counts, onRun }}
        >
        <CanvasMotionContext.Provider value={{ entering: enteringIds, drawing: drawingIds }}>
        <div
          ref={flowRootRef}
          className={
            appearance === "edit"
              ? "channel-canvas-stage"
              : "channel-canvas-stage channel-canvas-stage--browse"
          }
          onKeyDownCapture={onCanvasKeyDownCapture}
          onKeyDown={onCanvasKeyDown}
          onPointerDown={(event) => {
            setConnectNote(null);
            pointerRef.current = { x: event.clientX, y: event.clientY };
          }}
          onPointerMove={(event) => {
            pointerRef.current = { x: event.clientX, y: event.clientY };
          }}
          onPointerLeave={() => {
            pointerRef.current = null;
          }}
        >
          <ReactFlow
            colorMode={colorScheme}
            nodes={flowNodes}
            edges={flowEdges.map((edge) => ({
              ...edge,
              ariaLabel: t("channels.canvas.edge", {
                source: portLabel(t, edge.sourceHandle || "main"),
                target: portLabel(t, edge.targetHandle || "main"),
              }),
              className: [
                edge.className,
                phases.get(edge.target) === "running" ? "channel-flow-edge--live" : "",
                drawingIds.has(edge.id) && phases.get(edge.target) !== "running"
                  ? "channel-flow-edge--draw"
                  : "",
                phases.get(edge.source) === "dead" || phases.get(edge.target) === "dead"
                  ? "channel-flow-edge--settled"
                  : "",
                adjacentTo != null && (edge.source === adjacentTo || edge.target === adjacentTo)
                  ? "channel-flow-edge--adjacent"
                  : "",
              ]
                .filter(Boolean)
                .join(" ") || undefined,
            }))}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={{ type: CHANNEL_EDGE_TYPE, markerEnd: CHANNEL_EDGE_MARKER }}
            onNodesChange={onNodesChange}
            onNodeDragStart={onNodeDragStart}
            onNodeDragStop={onNodeDragStop}
            onEdgesChange={onEdgesChange}
            onNodeClick={(event, node) => {
              if (isNoteNode(node)) return;
              if (event.shiftKey || configNodeId == null) return;
              openNodeConfig(node.id);
            }}
            onNodeDoubleClick={(_, node) => {
              if (isNoteNode(node)) {
                if (mutable && appearance === "edit") {
                  if (noteEditOrigin.current?.id !== node.id) {
                    noteEditOrigin.current = { id: node.id, text: node.data.text };
                  }
                  setEditingNoteId(node.id);
                }
                return;
              }
              if (nodesRef.current.filter((item) => item.selected).length > 1) return;
              openNodeConfig(node.id);
            }}
            onConnect={onConnect}
            onConnectEnd={onConnectEnd}
            onPaneClick={beginClose}
            onNodeContextMenu={(event, node) => {
              event.preventDefault();
              event.stopPropagation();
              openNodeMenu(node.id, event.clientX, event.clientY);
            }}
            onSelectionContextMenu={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setContextMenu({ kind: "selection", x: event.clientX, y: event.clientY });
            }}
            onEdgeContextMenu={(event, edge) => {
              event.preventDefault();
              event.stopPropagation();
              if (!mutable || appearance !== "edit") return;
              setContextMenu({
                kind: "edge",
                edgeId: edge.id,
                x: event.clientX,
                y: event.clientY,
              });
            }}
            onPaneContextMenu={(event) => {
              event.preventDefault();
              openPaneMenu(event.clientX, event.clientY);
            }}
            isValidConnection={isValidConnection}
            nodesDraggable={mutable}
            nodesConnectable={mutable}
            elementsSelectable
            nodeDragThreshold={NODE_DRAG_THRESHOLD}
            nodeClickDistance={NODE_DRAG_THRESHOLD}
            multiSelectionKeyCode="Shift"
            selectionKeyCode="Shift"
            selectionMode={SelectionMode.Partial}
            deleteKeyCode={mutable ? ["Backspace", "Delete"] : null}
            zoomOnDoubleClick={false}
            snapToGrid
            snapGrid={[8, 8]}
            minZoom={CANVAS_MIN_ZOOM}
            maxZoom={CANVAS_MAX_ZOOM}
            fitView
          >
            {appearance === "edit" ? <Background gap={16} /> : null}
            {picker?.ghost ? <ConnectGhost ghost={picker.ghost} /> : null}
            <CanvasToolbar
              editing={appearance === "edit"}
              mutable={mutable}
              canUndo={canUndo}
              canRedo={canRedo}
              addExpanded={picker?.fromAdd ?? false}
              onAdd={openToolbarPicker}
              onAddNote={() => addNote(viewportCenter())}
              onUndo={undo}
              onRedo={redo}
              onSelectAll={selectAll}
              onCopy={() => {
                void writeFragment(selectedNodeIds());
              }}
              onCut={() => {
                const ids = selectedNodeIds();
                void writeFragment(ids).then((copied) => {
                  if (copied) removeNodes(ids);
                });
              }}
              onDuplicate={() => duplicateIds(selectedNodeIds())}
              onPaste={pasteText}
              overlayOpen={configNodeId != null || picker != null || leaving || contextMenu != null}
              catalog={catalog}
              problems={problems}
              problemGraph={labelGraph}
              activeProblemKey={highlight?.key ?? null}
              problemsDismissed={problemsDismissed}
              onFocusProblem={focusProblem}
              minZoom={CANVAS_MIN_ZOOM}
              maxZoom={CANVAS_MAX_ZOOM}
            />
          </ReactFlow>
          {connectNote ? (
            <Text
              className="channel-canvas-connect-note"
              style={{ left: connectNote.x, top: connectNote.y }}
              size="sm"
              c="dimmed"
              aria-live="polite"
            >
              {t(
                connectNote.message === "addRejected"
                  ? "channels.canvas.addRejected"
                  : "channels.canvas.connectNone",
              )}
            </Text>
          ) : null}
          {skipNote ? (
            <Text className="channel-canvas-clipboard-note" size="sm" c="dimmed" aria-live="polite">
              {skipNote}
            </Text>
          ) : null}
          {contextMenu ? (
            <CanvasContextMenu
              menu={contextMenu}
              editing={appearance === "edit"}
              mutable={mutable}
              onClose={closeMenu}
              onSettings={(nodeId) => {
                closeMenu();
                openNodeConfig(nodeId);
              }}
              onRun={(nodeId) => {
                closeMenu();
                onRun(nodeId);
              }}
              onDuplicate={() => {
                const ids =
                  contextMenu.kind === "node" || contextMenu.kind === "note"
                    ? [contextMenu.nodeId]
                    : selectedNodeIds();
                closeMenu();
                duplicateIds(ids);
              }}
              onCopy={() => {
                const ids =
                  contextMenu.kind === "node" || contextMenu.kind === "note"
                    ? [contextMenu.nodeId]
                    : selectedNodeIds();
                closeMenu();
                void writeFragment(ids);
              }}
              onCut={() => {
                const ids =
                  contextMenu.kind === "node" || contextMenu.kind === "note"
                    ? [contextMenu.nodeId]
                    : selectedNodeIds();
                closeMenu();
                void writeFragment(ids).then((copied) => {
                  if (copied) removeNodes(ids);
                });
              }}
              onDeleteNodes={() => {
                const ids =
                  contextMenu.kind === "node" || contextMenu.kind === "note"
                    ? [contextMenu.nodeId]
                    : selectedNodeIds();
                closeMenu();
                removeNodes(ids);
              }}
              onInsert={(edgeId, point) => {
                closeMenu();
                openPickerAt(point, { kind: "insertOnEdge", edgeId });
              }}
              onDeleteEdge={(edgeId) => {
                closeMenu();
                removeEdge(edgeId);
              }}
              onAdd={(point) => {
                closeMenu();
                openPickerAt(point, { kind: "free" });
              }}
              onAddNote={(point) => {
                closeMenu();
                addNote(screenToFlowPosition(point));
              }}
              onPaste={(text, point) => {
                closeMenu();
                const fragment = parseFragment(text);
                if (!fragment) return;
                applyAdded(
                  pasteFragment(fragment, graphNow(), catalog, heldPermissions, screenToFlowPosition(point)),
                );
              }}
              onFit={() => {
                closeMenu();
                void fitView({ duration: canvasViewportDuration() });
              }}
            />
          ) : null}
          {nodes.length === 0 ? (
            <div className="channel-canvas-empty">
              <EmptyState
                message={t("channels.canvas.empty")}
                action={
                  appearance === "edit" && mutable ? (
                    <Button
                      type="button"
                      size="xs"
                      variant="default"
                      onClick={(event) => {
                        const rect = event.currentTarget.getBoundingClientRect();
                        openAddPicker({ x: rect.left, y: rect.bottom }, false);
                      }}
                    >
                      {t("channels.canvas.add")}
                    </Button>
                  ) : null
                }
              />
            </div>
          ) : null}
          {selected ? (
            <Paper
              ref={overlayRef}
              withBorder
              shadow="md"
              p="sm"
              tabIndex={-1}
              aria-label={selected.data.name}
              className={[
                "channel-node-config",
                "channel-node-config--detail",
                leaving ? "channel-node-config--leave" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              aria-hidden={leaving || undefined}
              onPointerDown={(event) => event.stopPropagation()}
            >
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
                      nodes.flatMap((node) =>
                      isChannelNode(node)
                        ? [{
                            id: node.id,
                            ref: node.data.ref,
                            name: node.data.name,
                            parent: node.parentId,
                          }]
                        : [],
                    ),
                      edges.map((edge) => ({
                        source: edge.source,
                        target: edge.target,
                        sourcePort: edge.sourceHandle ?? undefined,
                        targetPort: edge.targetHandle ?? undefined,
                      })),
                      outputSchemas,
                      completion,
                    ),
                    context: {
                      channel: context?.channel ?? null,
                      run: context?.run ?? null,
                      platform: context?.platform ?? null,
                    },
                  }}
                  templatePreview={templatePreview}
                  recordedInput={sampleState.sample ? sampleState.sample.node.input : undefined}
                  baselineConfig={
                    sessionRun?.graph
                      ? (sessionRun.graph.nodes.find((node) => node.id === selected.id)?.config ?? {})
                      : null
                  }
                  sampleScope={sampleScope}
                  runTime={
                    sessionRun?.run.started_at ? showInstant(sessionRun.run.started_at) : null
                  }
                  onTemplateCaret={mutable ? onTemplateCaret : undefined}
                  phase={phases.get(selected.id) ?? null}
                  sampleBar={
                    sessionRun ? (
                      <SampleBar
                        run={sessionRun.run}
                        nodeId={selected.id}
                        nodes={runNodes}
                        sample={sampleState.sample}
                        loading={sampleState.loading}
                        channelId={channelId ?? ""}
                        jobId={sessionRun.run.job_id}
                        roundOf={roundOf}
                        totalOf={totalOf}
                        onRound={setRound}
                      />
                    ) : null
                  }
                  upstream={
                    <UpstreamRegion
                      channelId={channelId ?? ""}
                      jobId={sessionRun?.run.job_id ?? null}
                      hasUpstream={edges.some((edge) => edge.target === selected.id)}
                      detail={sessionRun}
                      sample={sampleState.sample}
                      loading={sampleState.loading}
                      failure={sampleState.failure}
                      catalog={catalog}
                      ports={ports}
                      roundOf={roundOf}
                      onOpenNode={openNodeConfig}
                      onInsert={mutable ? onInsert : undefined}
                      insertReady={insertReady}
                    />
                  }
                  result={
                    <ResultRegion
                      channelId={channelId ?? ""}
                      jobId={sessionRun?.run.job_id ?? null}
                      nodeId={selected.id}
                      nodeType={selected.data.nodeType}
                      nodes={runNodes}
                      detail={sessionRun}
                      sample={sampleState.sample}
                      loading={sampleState.loading}
                      failure={sampleState.failure}
                      catalog={catalog}
                      ports={ports}
                      graph={graph}
                      selectedRound={roundOf(selected.id)}
                      onRound={setRound}
                      onRoundsTotal={rememberRounds}
                    />
                  }
                  onClose={beginClose}
                  onChange={(nodeId, data) => {
                    const next = nodesRef.current.map((node) =>
                      node.id === nodeId && isChannelNode(node) ? { ...node, data } : node,
                    );
                    nodesRef.current = next;
                    setNodes(next);
                    emit(next, edgesRef.current);
                    commitNow();
                  }}
                  onRun={onRun}
                />
            </Paper>
          ) : null}
          {picker ? (
            <NodePicker
              key={picker.key}
              entries={pickerEntries}
              anchor={picker.anchor}
              frame={pickerFrame}
              preferAbove={picker.preferAbove}
              onSelect={chooseSpec}
              onClose={beginClose}
            />
          ) : null}
        </div>
        </CanvasMotionContext.Provider>
        </CanvasRunContext.Provider>
        </CanvasCatalogContext.Provider>
        </CanvasSurfaceContext.Provider>
    </Stack>
  );

  function paintProblems(
    currentNodes: CanvasNode[],
    currentEdges: Edge[],
    active: ProblemHighlight | null = highlightRef.current,
  ) {
    return {
      nodes: currentNodes.map((node) =>
        isNoteNode(node)
          ? node
          : {
              ...node,
              data: { ...node.data, problem: active?.nodeId === node.id },
            },
      ),
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
    return (
      connectionAllowed(graphNow(), catalog, connection) &&
      frameLinkAllowed(linkMembers(nodesRef.current), connection)
    );
  }

  function rememberEntering(ids: readonly string[]) {
    if (ids.length === 0 || prefersReducedMotion()) return;
    setEnteringIds((current) => {
      const next = new Set(current);
      for (const id of ids) next.add(id);
      return next;
    });
  }

  function rememberDrawing(ids: readonly string[], pool: readonly Edge[]) {
    if (ids.length === 0 || prefersReducedMotion()) return;
    const fresh = ids.filter((id) => {
      const edge = pool.find((item) => item.id === id);
      return edge != null && phases.get(edge.target) !== "running";
    });
    if (fresh.length === 0) return;
    setDrawingIds((current) => {
      const next = new Set(current);
      for (const id of fresh) next.add(id);
      return next;
    });
  }

  function forgetMotion() {
    setEnteringIds((current) => (current.size === 0 ? current : new Set()));
    setDrawingIds((current) => (current.size === 0 ? current : new Set()));
  }

  function releaseEntering(id: string) {
    setEnteringIds((current) => {
      if (!current.has(id)) return current;
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }

  function releaseDrawing(id: string) {
    setDrawingIds((current) => {
      if (!current.has(id)) return current;
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }

}

function snapshotOf(nodes: CanvasNode[], edges: Edge[]): CanvasSnapshot {
  return {
    nodes: nodes.map((node) =>
      isNoteNode(node)
        ? {
            ...settleNote(node),
            position: { ...node.position },
            selected: Boolean(node.selected),
            data: { text: node.data.text },
          }
        : {
            ...node,
            position: { ...node.position },
            selected: Boolean(node.selected),
            data: {
              ...node.data,
              problem: false,
              config: { ...node.data.config },
              retry: node.data.retry ? { ...node.data.retry } : null,
            },
          },
    ),
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
    nodes: snap.nodes.map((node) =>
      isNoteNode(node)
        ? {
            id: node.id,
            x: node.position.x,
            y: node.position.y,
            width: node.width,
            height: node.height,
            text: node.data.text,
          }
        : {
            id: node.id,
            x: node.position.x,
            y: node.position.y,
            type: node.data.nodeType,
            name: node.data.name,
            config: node.data.config,
            onError: node.data.onError,
            retry: node.data.retry,
            trigger: node.data.trigger,
            parent: node.parentId ?? null,
          },
    ),
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

function ConnectGhost({ ghost }: { ghost: PickerGhost }) {
  const { getInternalNode } = useReactFlow();
  const internal = getInternalNode(ghost.sourceId);
  const bounds = internal?.internals.handleBounds?.source ?? [];
  const handle = bounds.find((item) => (item.id ?? "main") === ghost.sourceHandle) ?? bounds[0];
  const sourceX = internal
    ? internal.internals.positionAbsolute.x +
      (handle ? handle.x + handle.width / 2 : (internal.measured.width ?? 208))
    : ghost.position.x;
  const sourceY = internal
    ? internal.internals.positionAbsolute.y +
      (handle ? handle.y + handle.height / 2 : (internal.measured.height ?? 56) / 2)
    : ghost.position.y + 28;
  const [path] = getBezierPath({
    sourceX,
    sourceY,
    targetX: ghost.position.x,
    targetY: ghost.position.y + 28,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  });
  return (
    <ViewportPortal>
      <svg
        className="channel-node-placeholder__edge"
        width={1}
        height={1}
        style={{ position: "absolute", overflow: "visible" }}
      >
        <path
          d={path}
          fill="none"
          stroke="var(--mantine-color-dimmed)"
          strokeDasharray="6 4"
          strokeWidth={1.5}
        />
      </svg>
      <div
        className="channel-node-placeholder"
        style={{
          position: "absolute",
          width: 208,
          height: 56,
          transform: `translate(${ghost.position.x}px, ${ghost.position.y}px)`,
        }}
      />
    </ViewportPortal>
  );
}

function CanvasContextMenu({
  menu,
  editing,
  mutable,
  onClose,
  onSettings,
  onRun,
  onDuplicate,
  onCopy,
  onCut,
  onDeleteNodes,
  onInsert,
  onDeleteEdge,
  onAdd,
  onAddNote,
  onPaste,
  onFit,
}: {
  menu: CanvasMenuState;
  editing: boolean;
  mutable: boolean;
  onClose: () => void;
  onSettings: (nodeId: string) => void;
  onRun: (nodeId: string) => void;
  onDuplicate: () => void;
  onCopy: () => void;
  onCut: () => void;
  onDeleteNodes: () => void;
  onInsert: (edgeId: string, point: { x: number; y: number }) => void;
  onDeleteEdge: (edgeId: string) => void;
  onAdd: (point: { x: number; y: number }) => void;
  onAddNote: (point: { x: number; y: number }) => void;
  onPaste: (text: string, point: { x: number; y: number }) => void;
  onFit: () => void;
}) {
  const t = useTranslate();
  const command = /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
  const canMutate = editing && mutable;
  const point = { x: menu.x, y: menu.y };
  const hint = (chord: ShortcutChord) => (
    <Text size="xs" c="dimmed">
      {formatShortcutChord(chord, command)}
    </Text>
  );
  const entries: ReactNode[] = [];
  if (menu.kind === "node") {
    entries.push(
      <Menu.Item
        key="settings"
        leftSection={<AdjustmentsIcon size={14} />}
        rightSection={hint({ key: "Enter" })}
        onClick={() => onSettings(menu.nodeId)}
      >
        {t("channels.node.settings")}
      </Menu.Item>,
    );
    if (editing) {
      entries.push(
        <Menu.Item
          key="run"
          disabled={!mutable}
          leftSection={<PlayIcon size={14} />}
          onClick={() => onRun(menu.nodeId)}
        >
          {t("channels.canvas.runToNode")}
        </Menu.Item>,
      );
    }
  }
  if ((menu.kind === "node" || menu.kind === "note" || menu.kind === "selection") && canMutate) {
    entries.push(
      <Menu.Item
        key="duplicate"
        leftSection={<DuplicateIcon size={14} />}
        rightSection={hint({ mod: true, key: "D" })}
        onClick={onDuplicate}
      >
        {t("channels.canvas.duplicate")}
      </Menu.Item>,
    );
  }
  if (menu.kind === "node" || menu.kind === "note" || menu.kind === "selection") {
    entries.push(
      <Menu.Item
        key="copy"
        leftSection={<CopyIcon size={14} />}
        rightSection={hint({ mod: true, key: "C" })}
        onClick={onCopy}
      >
        {t("channels.canvas.copy")}
      </Menu.Item>,
    );
  }
  if ((menu.kind === "node" || menu.kind === "note" || menu.kind === "selection") && canMutate) {
    entries.push(
      <Menu.Item
        key="cut"
        leftSection={<CutIcon size={14} />}
        rightSection={hint({ mod: true, key: "X" })}
        onClick={onCut}
      >
        {t("channels.canvas.cut")}
      </Menu.Item>,
      <Menu.Item
        key="delete"
        className="channel-canvas-menu__danger"
        leftSection={<CloseIcon size={14} />}
        rightSection={hint({ key: "Delete" })}
        onClick={onDeleteNodes}
      >
        {t("channels.node.delete")}
      </Menu.Item>,
    );
  }
  if (menu.kind === "edge" && canMutate) {
    entries.push(
      <Menu.Item
        key="insert"
        leftSection={<CanvasPlusIcon />}
        onClick={() => onInsert(menu.edgeId, point)}
      >
        {t("channels.canvas.insertNode")}
      </Menu.Item>,
      <Menu.Item
        key="delete-edge"
        className="channel-canvas-menu__danger"
        leftSection={<CloseIcon size={14} />}
        rightSection={hint({ key: "Delete" })}
        onClick={() => onDeleteEdge(menu.edgeId)}
      >
        {t("channels.node.delete")}
      </Menu.Item>,
    );
  }
  if (menu.kind === "pane") {
    if (canMutate) {
      entries.push(
        <Menu.Item key="add" leftSection={<CanvasPlusIcon />} onClick={() => onAdd(point)}>
          {t("channels.canvas.addHere")}
        </Menu.Item>,
        <Menu.Item key="add-note" leftSection={<NoteIcon size={14} />} onClick={() => onAddNote(point)}>
          {t("channels.canvas.addNote")}
        </Menu.Item>,
        <Menu.Item
          key="paste"
          disabled={menu.paste !== "ready"}
          leftSection={<PasteIcon size={14} />}
          rightSection={hint({ mod: true, key: "V" })}
          onClick={() => onPaste(menu.text, point)}
        >
          {t("channels.canvas.paste")}
        </Menu.Item>,
      );
    }
    entries.push(
      <Menu.Item
        key="fit"
        leftSection={<FitViewIcon size={14} />}
        rightSection={hint({ shift: true, key: "1" })}
        onClick={onFit}
      >
        {t("channels.canvas.fitView")}
      </Menu.Item>,
    );
  }
  if (entries.length === 0) return null;
  return (
    <Menu opened withinPortal position="bottom-start" offset={4} trapFocus={false} onClose={onClose}>
      <Menu.Target>
        <span
          aria-hidden
          style={{
            position: "fixed",
            left: menu.x,
            top: menu.y,
            width: 1,
            height: 1,
            pointerEvents: "none",
          }}
        />
      </Menu.Target>
      <Menu.Dropdown
        onContextMenu={(event) => {
          event.preventDefault();
        }}
      >
        {entries}
        {menu.kind === "pane" && menu.paste === "blocked" && canMutate ? (
          <Text size="xs" c="dimmed" px="sm" pb={4}>
            {t("channels.canvas.pasteShortcut")}
          </Text>
        ) : null}
      </Menu.Dropdown>
    </Menu>
  );
}

function problemGraphOf(nodes: CanvasNode[], edges: Edge[]): ProblemGraph {
  return {
    nodes: nodes.flatMap((node) =>
      isChannelNode(node) ? [{ id: node.id, name: node.data.name }] : [],
    ),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: { node_id: edge.source },
      target: { node_id: edge.target },
    })),
  };
}

function pointerStillOnEdge(target: EventTarget | null, edgeId: string): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest(".react-flow__edge")?.getAttribute("data-id") === edgeId) return true;
  if (target.closest(".react-flow__edge-toolbar")?.getAttribute("data-id") === edgeId) return true;
  if (target.closest(".channel-flow-edge__delete")?.getAttribute("data-edge-id") === edgeId) return true;
  return target.closest(".channel-flow-edge__insert")?.getAttribute("data-edge-id") === edgeId;
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
  const { editing, mutable, openPickerAt } = useContext(CanvasSurfaceContext);
  const drawing = useContext(CanvasMotionContext).drawing.has(id);
  const { deleteElements } = useReactFlow();
  const [hovered, setHovered] = useState(false);
  useLayoutEffect(() => {
    if (!drawing) return;
    const group = document.querySelector(`.react-flow__edge[data-id="${CSS.escape(id)}"]`);
    const path = group?.querySelector(".react-flow__edge-path");
    if (!(group instanceof SVGElement) || !(path instanceof SVGElement)) return;
    const measure = path as SVGElement & { getTotalLength?: () => number };
    if (typeof measure.getTotalLength !== "function") return;
    let length = 0;
    try {
      length = measure.getTotalLength();
    } catch {
      return;
    }
    if (!(length > 0)) return;
    group.style.setProperty("--channel-edge-length", `${length}`);
    path.style.animation = "none";
    void path.getBoundingClientRect();
    path.style.removeProperty("animation");
  }, [drawing, id]);
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
          <span className="channel-flow-edge__tools">
            {mutable ? (
              <FlowPlusButton
                className="channel-flow-edge__insert"
                edgeId={id}
                label={t("channels.canvas.insertNode")}
                onMouseEnter={enter}
                onMouseLeave={leave}
                onClick={(point) => openPickerAt(point, { kind: "insertOnEdge", edgeId: id })}
              />
            ) : null}
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
              <CloseIcon size={10} />
            </button>
          </span>
        </EdgeToolbar>
      ) : null}
    </>
  );
}

function NodeToolButton({
  label,
  className,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  className: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip label={label} openDelay={200}>
      <ActionIcon
        type="button"
        variant="default"
        size="sm"
        className={`${className} nodrag nopan`}
        aria-label={label}
        disabled={disabled}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onClick();
        }}
      >
        {children}
      </ActionIcon>
    </Tooltip>
  );
}

function NoteFlowNode({ id, data, selected }: NodeProps<Node<NoteData, "note">>) {
  const t = useTranslate();
  const { editing, mutable, editingNoteId, draftNoteText, endNoteEdit } = useContext(CanvasSurfaceContext);
  const entering = useContext(CanvasMotionContext).entering.has(id);
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const live = editingNoteId === id;
  const canEdit = editing && mutable;

  useEffect(() => {
    if (!live) return;
    fieldRef.current?.focus();
  }, [live]);

  return (
    <div
      className={entering ? "channel-note channel-flow-node--entering" : "channel-note"}
      aria-label={t("channels.canvas.noteLabel")}
    >
      {selected && canEdit ? (
        <NodeResizer
          minWidth={NOTE_MIN_WIDTH}
          minHeight={NOTE_MIN_HEIGHT}
          maxWidth={NOTE_MAX_SIZE}
          maxHeight={NOTE_MAX_SIZE}
          color="var(--mantine-color-yellow-light-color)"
        />
      ) : null}
      {live ? (
        <textarea
          ref={fieldRef}
          className="channel-note__input nodrag nowheel"
          maxLength={4000}
          value={data.text}
          aria-label={t("channels.canvas.noteLabel")}
          placeholder={t("channels.canvas.notePlaceholder")}
          onChange={(event) => draftNoteText(id, event.currentTarget.value)}
          onBlur={() => endNoteEdit(id)}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            event.currentTarget.blur();
          }}
        />
      ) : (
        <div className="channel-note__body">
          {data.text ? (
            data.text
          ) : (
            <span className="channel-note__placeholder">{t("channels.canvas.notePlaceholder")}</span>
          )}
        </div>
      )}
    </div>
  );
}

function ChannelFlowNode({ id, data, selected }: NodeProps<ChannelNode>) {
  const t = useTranslate();
  const { editing, mutable, openNode, openPickerAt, duplicateNode, busyOutputs } =
    useContext(CanvasSurfaceContext);
  const catalog = useContext(CanvasCatalogContext);
  const spec = catalog.find((item) => item.type === data.nodeType);
  const { deleteElements } = useReactFlow();
  const [hovered, setHovered] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const hideTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (hideTimer.current != null) window.clearTimeout(hideTimer.current);
    },
    [],
  );
  const showAdd = () => {
    if (hideTimer.current != null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    setHovered(true);
  };
  const scheduleHideAdd = (event: { relatedTarget: EventTarget | null }) => {
    const next = event.relatedTarget;
    const root = rootRef.current;
    if (root != null && next instanceof Node && root.contains(next)) return;
    if (hideTimer.current != null) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      setHovered(false);
    }, PORT_ADD_HIDE_MS);
  };
  const inputs = spec ? spec.inputs : data.trigger ? [] : [{ port: "main", description: "" }];
  const outputs = spec ? spec.outputs : [{ port: "main", description: "" }];
  const frame = isContainerNode(data.nodeType);
  const laid = layoutNodePorts(inputs, outputs, { frame });
  const errorAnchor = outputs.some((port) => port.port === "error");
  const run = useContext(CanvasRunContext);
  const entering = useContext(CanvasMotionContext).entering.has(id);
  const phase = run.phases.get(id);
  const phaseSeen = useRef(false);
  const phasePrior = useRef<string | null>(null);
  const [pop, setPop] = useState(false);
  useEffect(() => {
    const next = phase ?? null;
    if (!phaseSeen.current) {
      phaseSeen.current = true;
      phasePrior.current = next;
      return;
    }
    const prior = phasePrior.current;
    phasePrior.current = next;
    if (next === "succeeded" && (prior === "running" || prior == null) && !prefersReducedMotion()) {
      setPop(true);
    } else if (next !== "succeeded") {
      setPop(false);
    }
  }, [phase]);
  const presented = phase ? presentNodeStatus(phase) : null;
  const phaseStatus = presented
    ? {
        tone: presented.tone,
        labelKey: phase === "waiting" ? "channels.canvas.phase.waiting" : presented.labelKey,
      }
    : null;
  const count = run.counts.get(id) ?? 0;
  const onRun = run.onRun;
  const depth = Math.max(laid.inputs.length, laid.outputs.length, 1);
  const emphasis = data.problem
    ? "channel-flow-node--problem"
    : selected
      ? "channel-flow-node--selected"
      : "";
  const className = [
    "channel-flow-node",
    frame ? "channel-flow-node--frame" : "",
    emphasis,
    phase ? `channel-flow-node--${phase}` : "",
    entering ? "channel-flow-node--entering" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const family = spec?.family ?? "";
  const TypeIcon = nodeTypeIcon(data.nodeType, family);
  return (
    <div
      ref={rootRef}
      className={className}
      style={frame || depth <= 1 ? undefined : { minHeight: 24 + depth * 28 }}
      onMouseEnter={showAdd}
      onMouseLeave={scheduleHideAdd}
    >
      {editing ? (
        <NodeToolbar className="channel-node-toolbar" offset={8}>
          <NodeToolButton
            label={t("channels.node.settings")}
            className="channel-flow-node__settings"
            onClick={() => openNode(id)}
          >
            <AdjustmentsIcon size={14} />
          </NodeToolButton>
          <NodeToolButton
            label={t("channels.node.run")}
            className="channel-flow-node__run"
            disabled={!mutable}
            onClick={() => onRun(id)}
          >
            <PlayIcon size={14} />
          </NodeToolButton>
          <NodeToolButton
            label={t("channels.canvas.duplicate")}
            className="channel-flow-node__duplicate"
            disabled={!mutable}
            onClick={() => duplicateNode(id)}
          >
            <DuplicateIcon size={14} />
          </NodeToolButton>
          <NodeToolButton
            label={t("channels.node.delete")}
            className="channel-flow-node__delete"
            disabled={!mutable}
            onClick={() => {
              void deleteElements({ nodes: [{ id }] });
            }}
          >
            <CloseIcon size={14} />
          </NodeToolButton>
        </NodeToolbar>
      ) : null}
      <PortHandles ports={laid.inputs} nodeName={data.name} kind="target" />
      <span
        className={`channel-flow-node__icon channel-flow-node__icon--${familyTint(family)}`}
        aria-hidden
      >
        <TypeIcon />
      </span>
      <div className="channel-flow-node__body">
        <Text size="xs" c="dimmed">
          {spec ? nodeTypeLabel(t, spec) : data.nodeType}
        </Text>
        <Text size="sm" fw={600} className="channel-flow-node__name" title={data.name}>
          {data.name}
        </Text>
        {count > 1 ? (
          <Text size="xs" c="dimmed" className="channel-flow-node__count">
            {t("channels.run.executions", { count })}
          </Text>
        ) : null}
      </div>
      {phaseStatus && phase && isNodeRunPhase(phase) ? (
        <NodePhaseMark
          phase={phase}
          tone={phaseStatus.tone}
          label={t(phaseStatus.labelKey)}
          pop={pop}
          onPopEnd={() => setPop(false)}
        />
      ) : null}
      <PortHandles
        ports={laid.outputs}
        nodeName={data.name}
        kind="source"
        addable={editing && mutable && (hovered || Boolean(selected))}
        busyOutputs={busyOutputs}
        nodeId={id}
        onAddEnter={showAdd}
        onAddLeave={scheduleHideAdd}
        onAdd={(port, point) =>
          openPickerAt(point, { kind: "afterPort", sourceId: id, sourceHandle: port })
        }
      />
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

const PHASE_ICON: Record<NodeRunPhase, typeof CheckIcon> = {
  waiting: ClockIcon,
  running: LoaderIcon,
  succeeded: CheckIcon,
  failed: ErrorIcon,
  dead: CircleDashedIcon,
};

function isNodeRunPhase(phase: string): phase is NodeRunPhase {
  return Object.hasOwn(PHASE_ICON, phase);
}

function NodePhaseMark({
  phase,
  tone,
  label,
  pop,
  onPopEnd,
}: {
  phase: NodeRunPhase;
  tone: Tone;
  label: string;
  pop: boolean;
  onPopEnd: () => void;
}) {
  const Icon = PHASE_ICON[phase];
  const markRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = markRef.current;
    if (!node || !pop) return;
    const onEnd = (event: Event) => {
      if (event.target !== node) return;
      if (!("animationName" in event) || event.animationName !== "channel-flow-status-pop") return;
      onPopEnd();
    };
    node.addEventListener("animationend", onEnd);
    return () => node.removeEventListener("animationend", onEnd);
  }, [pop, onPopEnd]);
  return (
    <Tooltip label={label} openDelay={200}>
      <span
        ref={markRef}
        className={
          pop
            ? "channel-flow-node__status channel-flow-node__status--pop nodrag nopan"
            : "channel-flow-node__status nodrag nopan"
        }
        role="img"
        aria-label={label}
      >
        <Icon size={14} color={toneVariable(tone)} />
      </span>
    </Tooltip>
  );
}

function FlowPlusButton({
  className,
  label,
  edgeId,
  style,
  onMouseEnter,
  onMouseLeave,
  onClick,
}: {
  className?: string;
  label: string;
  edgeId?: string;
  style?: { top: string; left: string | number };
  onMouseEnter?: () => void;
  onMouseLeave?: (event: { relatedTarget: EventTarget | null }) => void;
  onClick: (point: { x: number; y: number }) => void;
}) {
  return (
    <button
      type="button"
      className={["channel-flow-plus nodrag nopan", className].filter(Boolean).join(" ")}
      style={style}
      data-edge-id={edgeId}
      aria-label={label}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onClick({ x: event.clientX, y: event.clientY });
      }}
    >
      <CanvasPlusIcon />
    </button>
  );
}

function PortHandles({
  ports,
  nodeName,
  kind,
  addable = false,
  busyOutputs,
  nodeId,
  onAdd,
  onAddEnter,
  onAddLeave,
}: {
  ports: readonly PortPlacement[];
  nodeName: string;
  kind: "target" | "source";
  addable?: boolean;
  busyOutputs?: ReadonlySet<string>;
  nodeId?: string;
  onAdd?: (port: string, point: { x: number; y: number }) => void;
  onAddEnter?: () => void;
  onAddLeave?: (event: { relatedTarget: EventTarget | null }) => void;
}) {
  const t = useTranslate();
  return (
    <>
      {ports.map((port) => {
        const name = portLabel(t, port.port);
        const occupied = busyOutputs?.has(`${nodeId}:${port.port}`) ?? false;
        const showAdd = kind === "source" && addable && !occupied && onAdd != null;
        return (
          <Fragment key={`${kind}-${port.port}`}>
            <Handle
              type={kind}
              position={flowPosition(port.position)}
              id={port.port}
              className={port.inset ? "channel-flow-handle--inset" : undefined}
              style={{ top: port.top }}
              aria-label={t("channels.canvas.handle", {
                node: nodeName,
                port: name,
                side: t(kind === "target" ? "channels.canvas.input" : "channels.canvas.output"),
              })}
              role="button"
            />
            {showAdd ? (
              <FlowPlusButton
                className={
                  port.inset
                    ? "channel-flow-port-add"
                    : "channel-flow-port-add channel-flow-port-add--outside"
                }
                style={
                  port.inset
                    ? { top: port.top, left: EACH_INSET + 16 }
                    : { top: port.top, left: "calc(100% + 16px)" }
                }
                label={t("channels.canvas.addFromPort", { port: name })}
                onMouseEnter={onAddEnter}
                onMouseLeave={onAddLeave}
                onClick={(point) => onAdd(port.port, point)}
              />
            ) : null}
            {port.labelled ? (
              <span
                className={`channel-flow-port channel-flow-port--${port.inset ? "inset" : port.position}`}
                style={{ top: port.top }}
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
  return side === "left" ? Position.Left : Position.Right;
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
