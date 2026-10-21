"use client";

import {
  ActionIcon,
  Button,
  Menu,
  Popover,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { MiniMap, Panel, useReactFlow, useViewport, type Node } from "@xyflow/react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  AlertIcon,
  ChevronDownIcon,
  FitViewIcon,
  KeyboardIcon,
  MinimapIcon,
  PlusIcon,
  RedoIcon,
  UndoIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "@/components/icons";
import { presentProblemSeverity, toneMantineColor } from "@/components/display/statusTone";
import { CanvasShortcuts } from "@/features/channels/CanvasShortcuts";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { familyTint } from "@/features/channels/nodeVisual";
import {
  formatGraphProblem,
  problemIdentity,
  type ProblemGraph,
} from "@/features/channels/problemLabel";
import type { GraphProblem, NodeTypeSpec } from "@/features/channels/types";
import {
  canvasViewportDuration,
  useCanvasShortcuts,
} from "@/features/channels/useCanvasShortcuts";

export const MINIMAP_STORAGE_KEY = "refraq.channelCanvas.minimap";

const PROBLEM_HOVER_CLOSE_MS = 120;
const ZOOM_LIMIT_EPSILON = 0.001;

export function readMinimapOpen(): boolean {
  try {
    return window.localStorage.getItem(MINIMAP_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeMinimapOpen(open: boolean): void {
  try {
    window.localStorage.setItem(MINIMAP_STORAGE_KEY, open ? "1" : "0");
  } catch {
    // Private mode and blocked storage must not take down the canvas.
  }
}

type ViewportCommand = "in" | "out" | "reset" | "fit";

export function CanvasToolbar({
  editing,
  mutable,
  canUndo,
  canRedo,
  addExpanded,
  onAdd,
  onUndo,
  onRedo,
  onSelectAll,
  catalog,
  problems,
  problemGraph,
  activeProblemKey,
  problemsDismissed,
  onFocusProblem,
  minZoom,
  maxZoom,
}: {
  editing: boolean;
  mutable: boolean;
  canUndo: boolean;
  canRedo: boolean;
  addExpanded: boolean;
  onAdd: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onSelectAll: () => void;
  catalog: readonly NodeTypeSpec[];
  problems: readonly GraphProblem[];
  problemGraph: ProblemGraph;
  activeProblemKey: string | null;
  problemsDismissed: number;
  onFocusProblem: (problem: GraphProblem) => void;
  minZoom: number;
  maxZoom: number;
}) {
  const t = useTranslate();
  const { zoomIn, zoomOut, zoomTo, fitView } = useReactFlow();
  const { zoom } = useViewport();
  const [helpOpen, setHelpOpen] = useState(false);
  const [minimapOpen, setMinimapOpen] = useState(readMinimapOpen);
  const percent = Math.round(zoom * 100);
  const zoomLabel = t("channels.canvas.zoomPercent", { percent });
  const atMin = zoom <= minZoom + ZOOM_LIMIT_EPSILON;
  const atMax = zoom >= maxZoom - ZOOM_LIMIT_EPSILON;

  const runViewport = (command: ViewportCommand) => {
    const duration = canvasViewportDuration();
    if (command === "in") void zoomIn({ duration });
    else if (command === "out") void zoomOut({ duration });
    else if (command === "reset") void zoomTo(1, { duration });
    else void fitView({ duration });
  };

  useCanvasShortcuts({
    mutable,
    undo: onUndo,
    redo: onRedo,
    fitView: () => runViewport("fit"),
    zoomIn: () => runViewport("in"),
    zoomOut: () => runViewport("out"),
    zoomTo100: () => runViewport("reset"),
    openHelp: () => setHelpOpen(true),
    selectAll: onSelectAll,
  });

  const toggleMinimap = () => {
    const next = !minimapOpen;
    writeMinimapOpen(next);
    setMinimapOpen(next);
  };

  return (
    <>
      <Panel position="bottom-left" className="nopan nodrag nowheel">
        <div
          className="channel-canvas-toolbar"
          role="toolbar"
          aria-label={t("channels.canvas.toolbar")}
        >
          {editing ? (
            <>
              <ToolButton
                label={t("channels.canvas.add")}
                disabled={!mutable}
                expanded={addExpanded}
                onClick={onAdd}
              >
                <PlusIcon size={14} />
              </ToolButton>
              <span className="channel-canvas-toolbar__sep" role="separator" />
              <ToolButton
                label={t("channels.canvas.undo")}
                disabled={!mutable || !canUndo}
                onClick={onUndo}
              >
                <UndoIcon size={14} />
              </ToolButton>
              <ToolButton
                label={t("channels.canvas.redo")}
                disabled={!mutable || !canRedo}
                onClick={onRedo}
              >
                <RedoIcon size={14} />
              </ToolButton>
              <span className="channel-canvas-toolbar__sep" role="separator" />
            </>
          ) : null}
          <ToolButton
            label={t("channels.canvas.zoomOut")}
            disabled={atMin}
            onClick={() => runViewport("out")}
          >
            <ZoomOutIcon size={14} />
          </ToolButton>
          <Menu position="top-start" withinPortal>
            <Menu.Target>
              <Tooltip label={zoomLabel} openDelay={200}>
                <ActionIcon
                  variant="subtle"
                  size="sm"
                  w="auto"
                  px={6}
                  aria-label={zoomLabel}
                >
                  {percent}%
                  <ChevronDownIcon size={12} />
                </ActionIcon>
              </Tooltip>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item disabled={atMax} onClick={() => runViewport("in")}>
                {t("channels.canvas.zoomIn")}
              </Menu.Item>
              <Menu.Item disabled={atMin} onClick={() => runViewport("out")}>
                {t("channels.canvas.zoomOut")}
              </Menu.Item>
              <Menu.Item onClick={() => runViewport("reset")}>
                {t("channels.canvas.zoom100")}
              </Menu.Item>
              <Menu.Item onClick={() => runViewport("fit")}>
                {t("channels.canvas.fitView")}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
          <ToolButton
            label={t("channels.canvas.zoomIn")}
            disabled={atMax}
            onClick={() => runViewport("in")}
          >
            <ZoomInIcon size={14} />
          </ToolButton>
          <ToolButton label={t("channels.canvas.fitView")} onClick={() => runViewport("fit")}>
            <FitViewIcon size={14} />
          </ToolButton>
          <ToolButton
            label={t("channels.canvas.minimap")}
            pressed={minimapOpen}
            onClick={toggleMinimap}
          >
            <MinimapIcon size={14} />
          </ToolButton>
          <span className="channel-canvas-toolbar__sep" role="separator" />
          {problems.length > 0 ? (
            <ProblemsControl
              problems={problems}
              graph={problemGraph}
              activeKey={activeProblemKey}
              dismissToken={problemsDismissed}
              onFocus={onFocusProblem}
            />
          ) : null}
          <ToolButton
            label={t("channels.canvas.shortcuts")}
            onClick={() => setHelpOpen(true)}
          >
            <KeyboardIcon size={14} />
          </ToolButton>
        </div>
      </Panel>
      {minimapOpen ? (
        <MiniMap
          position="bottom-right"
          pannable
          zoomable
          ariaLabel={t("channels.canvas.minimap")}
          nodeColor={(node: Node<FlowNodeData>) => {
            const family = catalog.find((item) => item.type === node.data.nodeType)?.family ?? "";
            return `var(--mantine-color-${familyTint(family)}-filled)`;
          }}
        />
      ) : null}
      <CanvasShortcuts
        opened={helpOpen}
        onClose={() => setHelpOpen(false)}
        userAgent={typeof navigator === "undefined" ? "" : navigator.userAgent}
      />
    </>
  );
}

function ToolButton({
  label,
  disabled,
  pressed,
  expanded,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  pressed?: boolean;
  expanded?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip label={label} openDelay={200}>
      <ActionIcon
        variant="subtle"
        size="sm"
        aria-label={label}
        aria-pressed={pressed}
        aria-expanded={expanded}
        disabled={disabled}
        onClick={onClick}
      >
        {children}
      </ActionIcon>
    </Tooltip>
  );
}

function ProblemsControl({
  problems,
  graph,
  activeKey,
  dismissToken,
  onFocus,
}: {
  problems: readonly GraphProblem[];
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
      position="top-start"
      withinPortal
    >
      <Popover.Target>
        <ActionIcon
          variant="subtle"
          size="sm"
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
          <AlertIcon size={14} />
          <span className="channel-canvas-problems__badge">{problems.length}</span>
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown onMouseEnter={enter} onMouseLeave={leave}>
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            {label}
          </Text>
          {problems.map((problem) => {
            const itemLabel = formatGraphProblem(t, problem, graph);
            const key = problemIdentity(problem);
            const toneName = presentProblemSeverity(problem.severity);
            const color = toneMantineColor(toneName);
            const tone =
              toneName === "warning" ? "channel-canvas-problems__item--warning" : undefined;
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
                className={
                  [tone, active ? "channel-canvas-problems__item--active" : undefined]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
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
