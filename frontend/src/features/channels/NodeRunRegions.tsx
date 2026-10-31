"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { listRounds, nodeSample } from "@/features/channels/api";
import { listItemProperties, readBatchOutput } from "@/features/channels/datasetView";
import { NodeRegion } from "@/features/channels/NodeRegion";
import { RunExecutionOutput, type OutputPick, type PathSegment } from "@/features/channels/RunExecutionOutput";
import { roundControlIds } from "@/features/channels/runSession";
import type {
  ChannelRun,
  ChannelRunDetail,
  ContainerDeclaration,
  Graph,
  NodeSample,
  NodeSampleScopeInput,
  NodeSampleUpstream,
  NodeTypeSpec,
  OutputView,
  RefinedPort,
} from "@/features/channels/types";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { problemMessage } from "@/lib/problem";

const GRAPH_DEBOUNCE_MS = 400;

export type RunNodeInfo = {
  id: string;
  name: string;
  ref: string;
  type: string;
  parent?: string;
  container: ContainerDeclaration | null;
};

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function useNodeSample({
  channelId,
  jobId,
  nodeId,
  graph,
  scope,
  recordedKey = "",
  containerRound,
  enabled,
}: {
  channelId: string;
  jobId: string | null;
  nodeId: string | null;
  graph: Graph;
  scope: readonly NodeSampleScopeInput[] | undefined;
  /** `recordedKey` of the live run. A change refetches without waiting for a graph edit. */
  recordedKey?: string;
  /** Selected round of a Container that declares Round Templates. Projects that round into `node.input`. */
  containerRound?: number;
  enabled: boolean;
}): { sample: NodeSample | null; loading: boolean; failure: unknown } {
  const [sample, setSample] = useState<NodeSample | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const graphRef = useRef(graph);
  graphRef.current = graph;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const graphKey = JSON.stringify(graph);
  const scopeKey = JSON.stringify(scope ?? null);
  const request = useRef(0);
  const previous = useRef<{ graphKey: string; other: string } | null>(null);
  const seenIdentity = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || !channelId || !jobId || !nodeId) {
      request.current += 1;
      setSample(null);
      setLoading(false);
      setFailure(null);
      seenIdentity.current = null;
      previous.current = null;
      return;
    }
    const identity = `${channelId}:${jobId}:${nodeId}`;
    const other = `${identity}:${scopeKey}:${recordedKey}:${containerRound ?? ""}`;
    const prior = previous.current;
    const graphChanged = prior != null && prior.graphKey !== graphKey;
    const otherChanged = prior == null || prior.other !== other;
    const delay = graphChanged && !otherChanged ? GRAPH_DEBOUNCE_MS : 0;
    previous.current = { graphKey, other };
    if (seenIdentity.current !== identity) {
      seenIdentity.current = identity;
      setSample(null);
      setFailure(null);
    }
    const id = ++request.current;
    setLoading(true);
    const timer = window.setTimeout(() => {
      const nextScope = scopeRef.current;
      void nodeSample(channelId, jobId, {
        graph: graphRef.current,
        node_id: nodeId,
        ...(nextScope && nextScope.length > 0 ? { scope: [...nextScope] } : {}),
        ...(typeof containerRound === "number" ? { container_round: containerRound } : {}),
      })
        .then((body) => {
          if (request.current !== id) return;
          setSample(body);
          setFailure(null);
        })
        .catch((reason: unknown) => {
          if (request.current !== id) return;
          setFailure(reason);
        })
        .finally(() => {
          if (request.current === id) setLoading(false);
        });
    }, delay);
    return () => {
      window.clearTimeout(timer);
      if (request.current === id) request.current += 1;
    };
  }, [enabled, channelId, jobId, nodeId, graphKey, scopeKey, recordedKey, containerRound]);

  return { sample, loading, failure };
}

export function SampleBar({
  run,
  nodeId,
  nodes,
  sample,
  loading,
  channelId,
  jobId,
  roundOf,
  totalOf,
  onRound,
}: {
  run: Pick<ChannelRun, "target" | "started_at" | "stop_at_node_id">;
  nodeId: string;
  nodes: readonly RunNodeInfo[];
  sample: NodeSample | null;
  loading: boolean;
  channelId: string;
  jobId: string;
  roundOf: (containerId: string) => number;
  totalOf: (containerId: string) => number;
  onRound: (containerId: string, round: number) => void;
}) {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const controls = roundControlIds(nodes, nodeId);
  return (
    <div className="channel-sample-bar" aria-busy={loading || undefined}>
      <Text size="xs">
        {t(run.target === "published" ? "channels.run.target.published" : "channels.run.target.draft")}
      </Text>
      <Text size="xs" c="dimmed">
        {t("channels.run.startedAt", { time: showInstant(run.started_at) })}
      </Text>
      <Text size="xs">
        {t(
          run.stop_at_node_id === nodeId
            ? "channels.run.stoppedAtThis"
            : "channels.run.notStoppedHere",
        )}
      </Text>
      {sample?.config_changed ? (
        <Text size="xs">{t("channels.run.configChanged")}</Text>
      ) : null}
      {loading ? (
        <Text size="xs" c="dimmed">
          {t("channels.run.sampleLoading")}
        </Text>
      ) : null}
      {controls.map((containerId) => (
        <RoundControl
          key={containerId}
          containerId={containerId}
          name={nodes.find((node) => node.id === containerId)?.name || containerId}
          round={roundOf(containerId)}
          total={totalOf(containerId)}
          seq={controlSeq(containerId, nodeId, sample)}
          channelId={channelId}
          jobId={jobId}
          onRound={onRound}
        />
      ))}
    </div>
  );
}

function RoundControl({
  containerId,
  name,
  round,
  total,
  seq,
  channelId,
  jobId,
  onRound,
}: {
  containerId: string;
  name: string;
  round: number;
  total: number;
  seq: number | null;
  channelId: string;
  jobId: string;
  onRound: (containerId: string, round: number) => void;
}) {
  const t = useTranslate();
  const [note, setNote] = useState<string | null>(null);
  const go = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const entered = Number(data.get("round"));
    if (!Number.isInteger(entered) || entered < 1) return;
    let next = entered - 1;
    if (total > 0) next = Math.min(next, total - 1);
    onRound(containerId, next);
  };
  return (
    <Group gap={4} wrap="nowrap" className="channel-round-control" aria-label={name}>
      <Text size="xs">{name}</Text>
      <Text size="xs">
        {total > 0 ? t("channels.run.round", { n: round + 1, total }) : t("channels.run.roundEmpty")}
      </Text>
      <Button
        size="compact-xs"
        variant="default"
        aria-label={t("channels.run.roundPrevious")}
        disabled={round <= 0}
        onClick={() => onRound(containerId, round - 1)}
      >
        {t("channels.run.roundPrevious")}
      </Button>
      <Button
        size="compact-xs"
        variant="default"
        aria-label={t("channels.run.roundNext")}
        disabled={total <= 0 || round >= total - 1}
        onClick={() => onRound(containerId, round + 1)}
      >
        {t("channels.run.roundNext")}
      </Button>
      <form onSubmit={go}>
        <input
          name="round"
          type="number"
          min={1}
          aria-label={t("channels.run.roundGo")}
          className="channel-round-go"
        />
      </form>
      <Button
        size="compact-xs"
        variant="default"
        disabled={seq == null || !channelId || !jobId}
        onClick={() => {
          if (seq == null || !channelId || !jobId) return;
          setNote(null);
          void firstFailedRound(channelId, jobId, seq)
            .then((found) => {
              if (found == null) setNote(t("channels.run.roundNoneFailed"));
              else onRound(containerId, found);
            })
            .catch(() => {
              setNote(t("channels.run.roundLookupFailed"));
            });
        }}
      >
        {t("channels.run.roundFirstFailed")}
      </Button>
      {note ? (
        <Text size="xs" c="dimmed">
          {note}
        </Text>
      ) : null}
    </Group>
  );
}

function controlSeq(containerId: string, nodeId: string, sample: NodeSample | null): number | null {
  if (!sample) return null;
  if (containerId === nodeId) return sample.node.seq;
  return sample.scope.find((level) => level.container_node_id === containerId)?.container_seq ?? null;
}

async function firstFailedRound(channelId: string, jobId: string, seq: number): Promise<number | null> {
  const limit = 200;
  let offset = 0;
  for (;;) {
    const page = await listRounds(channelId, jobId, seq, { limit, offset });
    const found = page.items.find((item) => (item.status_counts.failed ?? 0) > 0);
    if (found) return found.round;
    offset += page.items.length;
    if (page.items.length === 0 || offset >= page.total) return null;
  }
}

export function UpstreamRegion({
  channelId,
  jobId,
  hasUpstream,
  detail,
  sample,
  loading,
  failure,
  catalog,
  ports,
  roundOf,
  onOpenNode,
  onPick,
  onInsert,
  insertReady = false,
}: {
  channelId: string;
  jobId: string | null;
  hasUpstream: boolean;
  detail: ChannelRunDetail | null;
  sample: NodeSample | null;
  loading: boolean;
  failure: unknown;
  catalog: readonly NodeTypeSpec[];
  ports: readonly RefinedPort[];
  roundOf: (containerId: string) => number;
  onOpenNode?: (nodeId: string) => void;
  onPick?: OutputPick;
  /** Inserts a path into the template field that last had focus. */
  onInsert?: (ref: string, path: PathSegment[]) => void;
  /** False until a template field has been focused. */
  insertReady?: boolean;
}) {
  const t = useTranslate();
  const errorText = failure == null ? null : problemMessage(t, failure, t("channels.run.outputFailed"));
  const sentence = upstreamSentence(t, hasUpstream, detail, channelId, jobId, sample, loading, errorText);
  return (
    <NodeRegion title={t("channels.run.upstream")} tone="run">
      {errorText && sample ? (
        <Text size="xs" c="red" role="alert">
          {errorText}
        </Text>
      ) : null}
      {onInsert && !insertReady ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.focusRequired")}
        </Text>
      ) : null}
      {sentence || !sample ? (
        <Text size="sm" c="dimmed">
          {sentence}
        </Text>
      ) : (
        <UpstreamList
          channelId={channelId}
          jobId={jobId ?? ""}
          sample={sample}
          catalog={catalog}
          ports={ports}
          roundOf={roundOf}
          onOpenNode={onOpenNode}
          onPick={onPick}
          onInsert={onInsert}
          insertReady={insertReady}
        />
      )}
    </NodeRegion>
  );
}

function InsertPicks({ ready, children }: { ready: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const apply = () => {
      for (const button of root.querySelectorAll<HTMLButtonElement>("button.channel-view-pick")) {
        // The batch row expander only toggles rows. It does not insert a path.
        const disabled = button.hasAttribute("aria-expanded") ? false : !ready;
        if (button.disabled !== disabled) button.disabled = disabled;
      }
    };
    apply();
    // Round rows, the next page, and an expanded batch arrive after this commit.
    const observer = new MutationObserver(apply);
    observer.observe(root, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["class", "aria-expanded", "disabled"],
    });
    return () => observer.disconnect();
  }, [ready]);
  return (
    <div
      ref={ref}
      className="channel-upstream-picks"
      onMouseDown={(event) => {
        if (ready) event.preventDefault();
      }}
    >
      {children}
    </div>
  );
}

function upstreamSentence(
  t: Translate,
  hasUpstream: boolean,
  detail: ChannelRunDetail | null,
  channelId: string,
  jobId: string | null,
  sample: NodeSample | null,
  loading: boolean,
  error: string | null,
): string | null {
  if (!hasUpstream) return t("channels.run.noUpstream");
  if (detail == null) return t("channels.run.idle");
  if (!channelId || !jobId) return t("channels.run.empty");
  if (error && !sample) return error;
  if (loading && !sample) return t("channels.run.sampleLoading");
  if (!sample) return t("channels.run.empty");
  if (sample.upstream.length === 0) return t("channels.run.empty");
  return null;
}

function UpstreamList({
  channelId,
  jobId,
  sample,
  catalog,
  ports,
  roundOf,
  onOpenNode,
  onPick,
  onInsert,
  insertReady,
}: {
  channelId: string;
  jobId: string;
  sample: NodeSample;
  catalog: readonly NodeTypeSpec[];
  ports: readonly RefinedPort[];
  roundOf: (containerId: string) => number;
  onOpenNode?: (nodeId: string) => void;
  onPick?: OutputPick;
  onInsert?: (ref: string, path: PathSegment[]) => void;
  insertReady: boolean;
}) {
  const t = useTranslate();
  const referenced = sample.upstream.filter((item) => item.referenced);
  const others = sample.upstream.filter((item) => !item.referenced);
  return (
    <Stack gap="sm">
      {referenced.map((entry) => (
        <UpstreamEntry
          key={entry.node_id}
          channelId={channelId}
          jobId={jobId}
          entry={entry}
          catalog={catalog}
          ports={ports}
          round={roundOf(entry.node_id)}
          onOpenNode={onOpenNode}
          onPick={onPick}
          onInsert={onInsert}
          insertReady={insertReady}
        />
      ))}
      {others.length > 0 ? (
        <details className="channel-upstream-other">
          <summary>{t("channels.run.otherUpstream")}</summary>
          <Stack gap="sm">
            {others.map((entry) => (
              <UpstreamEntry
                key={entry.node_id}
                channelId={channelId}
                jobId={jobId}
                entry={entry}
                catalog={catalog}
                ports={ports}
                round={roundOf(entry.node_id)}
                onOpenNode={onOpenNode}
                onPick={onPick}
                onInsert={onInsert}
                insertReady={insertReady}
              />
            ))}
          </Stack>
        </details>
      ) : null}
    </Stack>
  );
}

function UpstreamEntry({
  channelId,
  jobId,
  entry,
  catalog,
  ports,
  round,
  onOpenNode,
  onPick,
  onInsert,
  insertReady = false,
}: {
  channelId: string;
  jobId: string;
  entry: NodeSampleUpstream;
  catalog: readonly NodeTypeSpec[];
  ports: readonly RefinedPort[];
  round: number;
  onOpenNode?: (nodeId: string) => void;
  onPick?: OutputPick;
  onInsert?: (ref: string, path: PathSegment[]) => void;
  insertReady?: boolean;
}) {
  const t = useTranslate();
  const view = viewFor(catalog, entry.type_id);
  const level = entry.source === "round_step";
  const ref = entry.ref;
  const pick =
    onInsert && ref && insertReady ? (path: PathSegment[]) => onInsert(ref, path) : onPick;
  const output =
    entry.state !== "not_recorded" && entry.value != null ? (
      <RunExecutionOutput
        channelId={channelId}
        jobId={jobId}
        value={entry.value}
        view={view}
        truncated={entry.truncated}
        totals={entry.totals}
        seq={entry.seq}
        previewOnly={entry.preview_only}
        onPick={pick}
        rowProperties={rowProperties(ports, entry.node_id, view)}
        stepItem={level ? (view?.item ?? null) : null}
        iterations={isForIterations(entry)}
        metricsOnly={isBatchDone(entry)}
      />
    ) : null;
  return (
    <Stack gap={4} className="channel-upstream-entry">
      <Group gap={6} wrap="nowrap">
        <Text size="xs" fw={600}>
          {entry.name || entry.ref || entry.node_id}
        </Text>
        {level ? (
          <button type="button" className="channel-view-pick" onClick={() => onOpenNode?.(entry.node_id)}>
            {t("channels.run.roundBadge", { n: round + 1 })}
          </button>
        ) : null}
      </Group>
      {entry.ref ? (
        <Text size="xs" c="dimmed">
          {`self.${entry.ref}.output`}
        </Text>
      ) : null}
      {entry.state === "not_recorded" ? (
        <Text size="xs" c="dimmed">
          {t("channels.run.notRecorded")}
        </Text>
      ) : null}
      {entry.state === "failed" ? (
        <Text size="xs" c="red">
          {t("channels.run.upstreamFailed")}
        </Text>
      ) : null}
      {entry.error ? (
        <Text size="xs" c="red">
          {entry.error.message || entry.error.code}
        </Text>
      ) : null}
      {onInsert && output ? (
        <InsertPicks ready={Boolean(ref) && insertReady}>{output}</InsertPicks>
      ) : (
        output
      )}
    </Stack>
  );
}

export function ResultRegion({
  channelId,
  jobId,
  nodeId,
  nodeType,
  nodes,
  detail,
  sample,
  loading,
  failure,
  catalog,
  ports,
  graph,
  selectedRound,
  onRound,
  onRoundsTotal,
  onPick,
  recordedKey = "",
}: {
  channelId: string;
  jobId: string | null;
  nodeId: string;
  nodeType: string;
  nodes: readonly RunNodeInfo[];
  detail: ChannelRunDetail | null;
  sample: NodeSample | null;
  loading: boolean;
  failure: unknown;
  catalog: readonly NodeTypeSpec[];
  ports: readonly RefinedPort[];
  graph: Graph | null;
  selectedRound: number | null;
  onRound: (containerId: string, round: number) => void;
  onRoundsTotal: (containerId: string, total: number) => void;
  onPick?: OutputPick;
  recordedKey?: string;
}) {
  const t = useTranslate();
  const errorText = failure == null ? null : problemMessage(t, failure, t("channels.run.outputFailed"));
  const sentence = resultSentence(t, detail, channelId, jobId, sample, loading, errorText);
  const bodyStopId =
    sample?.node.error?.code === "CHANNEL_LOOP_BODY_STOPPED" ? detail?.run.failed_node_id : null;
  const bodyStopName = bodyStopId
    ? nodes.find((node) => node.id === bodyStopId)?.name.trim() || bodyStopId
    : null;
  const view = viewFor(catalog, nodeType);
  const output = sample?.node.output;
  const batch = readBatchOutput(output);
  return (
    <NodeRegion title={t("channels.run.result")} tone="run">
      {errorText && sample ? (
        <Text size="xs" c="red" role="alert">
          {errorText}
        </Text>
      ) : null}
      {sentence ? (
        <Text size="sm" c="dimmed">
          {sentence}
        </Text>
      ) : sample ? (
        <Stack gap={4}>
          {sample.node.state === "failed" || sample.node.state === "skipped" ? (
            <Text size="xs">
              {t(sample.node.state === "failed" ? "channels.run.upstreamFailed" : "channels.run.skipped")}
            </Text>
          ) : null}
          {bodyStopName ? (
            <Text size="xs">{t("channels.run.bodyStoppedBy", { name: bodyStopName })}</Text>
          ) : null}
          <RunExecutionOutput
          channelId={channelId}
          jobId={jobId ?? ""}
          value={output}
          view={view}
          error={
            sample.node.state === "failed" || sample.node.state === "skipped" ? sample.node.error : null
          }
          truncated={sample.node.output_truncated}
          totals={sample.node.totals}
          seq={sample.node.seq}
          previewOnly={sample.node.preview_only}
          onPick={onPick}
          rowProperties={
            view?.kind === "container"
              ? currentProperties(ports, nodeId)
              : rowProperties(ports, nodeId, view)
          }
          graph={graph}
          selectedRound={selectedRound}
          onSelectRound={(round) => onRound(nodeId, round)}
          onRoundsTotal={(total) => onRoundsTotal(nodeId, total)}
          batchChildId={nodes.find((node) => node.parent === nodeId)?.id ?? null}
          batchSize={batch?.batchSize ?? null}
          recordedKey={recordedKey}
        />
        </Stack>
      ) : null}
    </NodeRegion>
  );
}

function resultSentence(
  t: Translate,
  detail: ChannelRunDetail | null,
  channelId: string,
  jobId: string | null,
  sample: NodeSample | null,
  loading: boolean,
  error: string | null,
): string | null {
  if (detail == null) return t("channels.run.idle");
  if (!channelId || !jobId) return t("channels.run.absent");
  if (error && !sample) return error;
  if (loading && !sample) return t("channels.run.sampleLoading");
  if (!sample || sample.node.state === "not_recorded") return t("channels.run.absent");
  if (sample.node.state === "running") return t("channels.run.running");
  return null;
}

function viewFor(catalog: readonly NodeTypeSpec[], typeId: string): OutputView | null {
  return catalog.find((item) => item.type === typeId)?.output_view ?? null;
}

function rowProperties(
  ports: readonly RefinedPort[],
  nodeId: string,
  view: OutputView | null,
): string[] {
  if (!view || (view.kind !== "rows" && view.kind !== "container")) return [];
  const key = view.kind === "rows" ? (view.rows ?? "rows") : (view.item ?? "");
  if (!key) return [];
  const schema = ports.find(
    (port) => port.node_id === nodeId && port.direction === "output" && port.port === "main",
  )?.schema;
  return listItemProperties(schema, key);
}

function currentProperties(ports: readonly RefinedPort[], nodeId: string): string[] {
  const schema = ports.find(
    (port) => port.node_id === nodeId && port.direction === "output" && port.port === "each",
  )?.schema;
  const current = schema?.properties?.current;
  if (!current || Array.isArray(current)) return [];
  return Object.keys(current.properties ?? {});
}

function isBatchDone(entry: NodeSampleUpstream): boolean {
  return entry.source === "execution" && entry.type_id === "volume.batch_read";
}

function isForIterations(entry: NodeSampleUpstream): boolean {
  return (
    entry.source === "execution" &&
    (entry.type_id === "volume.for" || entry.type_id === "volume.until") &&
    typeof entry.value === "object" &&
    entry.value !== null &&
    !Array.isArray(entry.value) &&
    Array.isArray((entry.value as { iterations?: unknown }).iterations)
  );
}
