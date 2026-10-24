"use client";

import { Code, Pagination, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { getExecutionOutput, listRounds } from "@/features/channels/api";
import { BatchRoundRows } from "@/features/channels/BatchRoundRows";
import { DatasetCard, DatasetRowTable } from "@/features/channels/DatasetRows";
import {
  batchOrdWindow,
  datasetReferencesIn,
  isDatasetReference,
  readBatchOutput,
  rowColumnKeys,
  type DatasetReference,
} from "@/features/channels/datasetView";
import { RunErrorText } from "@/features/channels/RunErrorText";
import type {
  ContainerRound,
  Graph,
  NodeExecution,
  OutputView,
} from "@/features/channels/types";
import { copyText } from "@/lib/copy-text";
import { pageCountOf } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";

const ROW_PAGE = 100;
const ROUND_PAGE = 50;

export type PathSegment = string | number;
export type OutputPick = (path: PathSegment[]) => void;

type ShownError = { code: string | null; message: string | null } | null;

export function RunExecutionOutput({
  channelId,
  jobId,
  item,
  value,
  view = null,
  error,
  truncated,
  totals,
  previewOnly,
  seq,
  onPick,
  rowProperties = [],
  graph = null,
  stepItem = null,
  iterations = false,
  metricsOnly = false,
  selectedRound = null,
  onSelectRound,
  onRoundsTotal,
  batchChildId = null,
  batchSize = null,
  containerId,
}: {
  channelId: string;
  jobId: string;
  /** Execution-browser row. The panel passes `value` instead. */
  item?: NodeExecution;
  value?: unknown;
  view?: OutputView | null;
  error?: ShownError;
  truncated?: boolean;
  totals?: Record<string, number>;
  previewOnly?: boolean;
  seq?: number | null;
  onPick?: OutputPick;
  /** Schema property names of the row element, in declaration order. */
  rowProperties?: readonly string[];
  graph?: Graph | null;
  /** Round-step key (`current` or `rows`) when this value is a Container Round. */
  stepItem?: string | null;
  /** For output read from `done`: `iterations` is one row per round. */
  iterations?: boolean;
  /** Batch Read output read from `done`: metric badges, not the round table. */
  metricsOnly?: boolean;
  selectedRound?: number | null;
  onSelectRound?: (round: number) => void;
  onRoundsTotal?: (total: number) => void;
  batchChildId?: string | null;
  batchSize?: number | null;
  /** Container whose direct child reconstructs an expanded batch. Defaults to `item.node_id`. */
  containerId?: string | null;
}) {
  const shownValue = value !== undefined ? value : item?.output_preview;
  const shownError = error !== undefined ? error : errorOf(item);
  const shownTruncated = truncated ?? item?.output_truncated ?? false;
  const shownTotals = totals ?? item?.preview_totals ?? {};
  const shownPreview = previewOnly ?? item?.preview_only ?? false;
  const shownSeq = seq !== undefined ? seq : (item?.seq ?? null);
  const shownContainer = containerId !== undefined ? containerId : (item?.node_id ?? null);
  return (
    <OutputBody
      channelId={channelId}
      jobId={jobId}
      value={shownValue}
      view={view}
      error={shownError}
      truncated={shownTruncated}
      totals={shownTotals}
      previewOnly={shownPreview}
      seq={shownSeq}
      onPick={onPick}
      rowProperties={rowProperties}
      graph={graph}
      stepItem={stepItem}
      iterations={iterations}
      metricsOnly={metricsOnly}
      selectedRound={selectedRound}
      onSelectRound={onSelectRound}
      onRoundsTotal={onRoundsTotal}
      batchChildId={batchChildId}
      batchSize={batchSize}
      containerId={shownContainer}
    />
  );
}

function errorOf(item: NodeExecution | undefined): ShownError {
  if (!item || (!item.error_code && !item.error_message)) return null;
  return { code: item.error_code, message: item.error_message };
}

type BodyProps = {
  channelId: string;
  jobId: string;
  value: unknown;
  view: OutputView | null;
  error: ShownError;
  truncated: boolean;
  totals: Record<string, number>;
  previewOnly: boolean;
  seq: number | null;
  onPick?: OutputPick;
  rowProperties: readonly string[];
  graph: Graph | null;
  stepItem: string | null;
  iterations: boolean;
  metricsOnly: boolean;
  selectedRound: number | null;
  onSelectRound?: (round: number) => void;
  onRoundsTotal?: (total: number) => void;
  batchChildId: string | null;
  batchSize: number | null;
  containerId: string | null;
};

function OutputBody(props: BodyProps) {
  const t = useTranslate();
  const { error, previewOnly, totals } = props;
  return (
    <Stack gap={4}>
      {previewOnly ? (
        <Stack gap={2}>
          <Text size="xs">{t("channels.run.previewOnly")}</Text>
          {Object.entries(totals).map(([path, count]) => (
            <Text key={path} size="xs" c="dimmed">
              {t("channels.run.previewTotal", { path, count })}
            </Text>
          ))}
        </Stack>
      ) : null}
      {error && (error.code || error.message) ? (
        <Text size="xs" c="red">
          <RunErrorText code={error.code} message={error.message} />
        </Text>
      ) : null}
      <ViewSwitch {...props} />
    </Stack>
  );
}

function ViewSwitch(props: BodyProps) {
  const { view, value, stepItem, iterations } = props;
  if (stepItem) return <StepView {...props} itemKey={stepItem} />;
  if (iterations) return <IterationsView {...props} />;
  if (props.metricsOnly) {
    return <MetricBadges keys={view?.metrics ?? []} value={value} onPick={props.onPick} />;
  }
  if (view?.kind === "container") return <ContainerView {...props} />;
  if (view?.kind === "record") return <RecordView {...props} />;
  if (view?.kind === "rows") return <RowsKind {...props} />;
  if (view?.kind === "dataset") return <DatasetKind {...props} />;
  if (view?.kind === "counts") return <CountsKind {...props} />;
  if (view?.kind === "value") return <ValueKind value={value} onPick={props.onPick} />;
  return <FallbackValue {...props} />;
}

function metricLabel(t: (key: string) => string, key: string): string {
  const localeKey = `channels.view.metric.${key}`;
  const label = t(localeKey);
  return label === localeKey ? key : label;
}

function MetricBadges({
  keys,
  value,
  onPick,
}: {
  keys: readonly string[];
  value: unknown;
  onPick?: OutputPick;
}) {
  const t = useTranslate();
  const record = isRecord(value) ? value : null;
  if (!record) return null;
  const present = keys.filter((key) => Object.prototype.hasOwnProperty.call(record, key));
  if (present.length === 0) return null;
  return (
    <div className="channel-view-metrics">
      {present.map((key) => (
        <button
          key={key}
          type="button"
          className="channel-view-metric channel-view-pick"
          onClick={() => onPick?.([key])}
        >
          <span>{metricLabel(t, key)}</span>
          <span>{scalarText(record[key])}</span>
        </button>
      ))}
    </div>
  );
}

function RecordView({ value, view, onPick }: BodyProps) {
  const metrics = view?.metrics ?? [];
  return (
    <Stack gap={4}>
      <MetricBadges keys={metrics} value={value} onPick={onPick} />
      <RecordTree value={omitKeys(value, metrics)} path={[]} onPick={onPick} />
    </Stack>
  );
}

function RecordTree({
  value,
  path,
  onPick,
}: {
  value: unknown;
  path: PathSegment[];
  onPick?: OutputPick;
}) {
  const t = useTranslate();
  if (!isRecord(value)) {
    return <span>{scalarText(value)}</span>;
  }
  const entries = Object.entries(value);
  if (entries.length === 0) return <span>{"{}"}</span>;
  return (
    <div className="channel-view-tree">
      {entries.map(([key, child]) => {
        const childPath = [...path, key];
        const nested = isRecord(child);
        return (
          <div key={key}>
            <button type="button" className="channel-view-pick" onClick={() => onPick?.(childPath)}>
              {key}
            </button>
            {nested ? (
              <details>
                <summary>{t("channels.view.nested")}</summary>
                <RecordTree value={child} path={childPath} onPick={onPick} />
              </details>
            ) : (
              <span>{` ${scalarText(child)}`}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function RowsKind(props: BodyProps) {
  const listKey = props.view?.rows ?? "rows";
  const rows = isRecord(props.value) && Array.isArray(props.value[listKey]) ? props.value[listKey] : [];
  return (
    <Stack gap={4}>
      <MetricBadges keys={props.view?.metrics ?? []} value={props.value} onPick={props.onPick} />
      <RowsTable
        {...props}
        listKey={listKey}
        path={[listKey]}
        embedded={rows}
        rowProperties={props.rowProperties}
      />
    </Stack>
  );
}

function RowsTable({
  channelId,
  jobId,
  seq,
  listKey,
  path,
  embedded,
  totals,
  truncated,
  previewOnly,
  rowProperties,
  onPick,
}: BodyProps & {
  listKey: string;
  path: PathSegment[];
  embedded: readonly unknown[];
}) {
  const t = useTranslate();
  const [page, setPage] = useState(1);
  const [remote, setRemote] = useState<{ page: number; items: unknown[]; total: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const knownTotal = totals[listKey];
  const total = remote?.total ?? knownTotal ?? embedded.length;

  useEffect(() => {
    setPage(1);
    setRemote(null);
    setFailed(false);
  }, [channelId, jobId, seq, listKey]);

  useEffect(() => {
    if (previewOnly || seq == null || (page === 1 && (knownTotal != null || !truncated))) {
      setFailed(false);
      return;
    }
    let cancelled = false;
    setFailed(false);
    void getExecutionOutput(channelId, jobId, seq, {
      path: listKey,
      limit: ROW_PAGE,
      offset: (page - 1) * ROW_PAGE,
    })
      .then((body) => {
        if (cancelled) return;
        if ("items" in body && Array.isArray(body.items) && typeof body.total === "number") {
          setRemote({ page, items: body.items, total: body.total });
          return;
        }
        setRemote((current) => (current?.page === page ? null : current));
        setFailed(true);
      })
      .catch(() => {
        if (cancelled) return;
        setRemote((current) => (current?.page === page ? null : current));
        setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [previewOnly, seq, page, knownTotal, truncated, channelId, jobId, listKey]);

  const shown = page === 1 ? embedded.slice(0, ROW_PAGE) : remote?.page === page ? remote.items : [];
  const offset = (page - 1) * ROW_PAGE;
  const columns = rowColumnKeys(rowProperties, shown);
  const scalar = columns.length === 0;
  const pageCount =
    previewOnly || seq == null ? 1 : Math.max(1, pageCountOf(total, ROW_PAGE));
  return (
    <Stack gap={4}>
      <Text size="xs" c="dimmed">
        {t("channels.run.showingRows", { shown: shown.length, total })}
      </Text>
      {failed ? (
        <Text size="xs" c="red" role="alert">
          {t("channels.run.rowsFailed")}
        </Text>
      ) : null}
      <Table>
        <Table.Thead>
          <Table.Tr>
            {(scalar ? [t("channels.run.column.value")] : columns).map((column) => (
              <Table.Th key={column}>
                <button type="button" className="channel-view-pick" onClick={() => onPick?.(path)}>
                  {column}
                </button>
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {shown.map((row, index) => {
            const absolute = offset + index;
            return (
              <Table.Tr key={absolute}>
                {scalar ? (
                  <Table.Td>
                    <button
                      type="button"
                      className="channel-view-pick"
                      onClick={() => onPick?.([...path, absolute])}
                    >
                      {scalarText(row)}
                    </button>
                  </Table.Td>
                ) : (
                  columns.map((column) => (
                    <Table.Td key={column}>
                      <button
                        type="button"
                        className="channel-view-pick"
                        onClick={() => onPick?.([...path, absolute, column])}
                      >
                        {scalarText(isRecord(row) ? row[column] : undefined)}
                      </button>
                    </Table.Td>
                  ))
                )}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {pageCount > 1 ? (
        <Pagination value={page} onChange={setPage} total={pageCount} size="xs" />
      ) : null}
    </Stack>
  );
}

function DatasetKind(props: BodyProps) {
  const t = useTranslate();
  const key = props.view?.dataset ?? "dataset";
  const raw = isRecord(props.value) ? props.value[key] : null;
  const dataset = isDatasetReference(raw) ? raw : null;
  return (
    <Stack gap={4}>
      <MetricBadges keys={props.view?.metrics ?? []} value={props.value} onPick={props.onPick} />
      {dataset ? (
        <DatasetBlock
          channelId={props.channelId}
          jobId={props.jobId}
          dataset={dataset}
          path={[key]}
          onPick={props.onPick}
        />
      ) : (
        <Text size="xs" c="dimmed">
          {t("channels.run.notRecorded")}
        </Text>
      )}
    </Stack>
  );
}

function DatasetBlock({
  channelId,
  jobId,
  dataset,
  path,
  onPick,
}: {
  channelId: string;
  jobId: string;
  dataset: DatasetReference;
  path: PathSegment[];
  onPick?: OutputPick;
}) {
  const t = useTranslate();
  const [copyFailed, setCopyFailed] = useState(false);
  return (
    <Stack gap={4}>
      <Text size="xs">
        {dataset.columns.map((column) => `${column.name} (${column.type})`).join(", ")}
      </Text>
      <Text size="xs" c="dimmed">
        {t("channels.run.dataset.count", { count: dataset.count })}
      </Text>
      <button
        type="button"
        className="channel-view-pick channel-dataset-id"
        aria-label={t("channels.run.copyDatasetId", { id: dataset.dataset_id })}
        onClick={() => {
          onPick?.([...path, "dataset_id"]);
          void copyText(dataset.dataset_id).then(
            () => setCopyFailed(false),
            () => setCopyFailed(true),
          );
        }}
      >
        {dataset.dataset_id}
      </button>
      {copyFailed ? (
        <Text size="xs" c="red" role="alert">
          {t("common.copy.failed")}
        </Text>
      ) : null}
      <DatasetRowTable
        channelId={channelId}
        jobId={jobId}
        datasetId={dataset.dataset_id}
        afterOrd={0}
        endOrd={dataset.count}
        columns={dataset.columns}
        hideOrd
        onHeaderPick={() => onPick?.(path)}
        onCellPick={() => onPick?.(path)}
      />
    </Stack>
  );
}

function CountsKind({ value, view, onPick }: BodyProps) {
  const metrics = view?.metrics ?? [];
  const extra = isRecord(value) ? Object.keys(value).filter((key) => !metrics.includes(key)) : [];
  return <MetricBadges keys={[...metrics, ...extra]} value={value} onPick={onPick} />;
}

function ValueKind({ value, onPick }: { value: unknown; onPick?: OutputPick }) {
  const text = JSON.stringify(value, null, 2);
  if (!onPick) return <Code block>{text}</Code>;
  return (
    <button type="button" className="channel-view-pick" onClick={() => onPick([])}>
      <Code block>{text}</Code>
    </button>
  );
}

function FallbackValue({ value, previewOnly, channelId, jobId }: BodyProps) {
  const references = datasetReferencesIn(value);
  if (references.length > 0) {
    return (
      <Stack gap={4}>
        {references.map((dataset) => (
          <DatasetCard
            key={dataset.dataset_id}
            channelId={channelId}
            jobId={jobId}
            dataset={dataset}
          />
        ))}
      </Stack>
    );
  }
  if (previewOnly && value == null) return null;
  return <Code block>{JSON.stringify(value, null, 2)}</Code>;
}

function StepView({ itemKey, ...props }: BodyProps & { itemKey: string }) {
  const record = isRecord(props.value) ? props.value : null;
  const item = record ? record[itemKey] : undefined;
  const metricKeys = record ? Object.keys(record).filter((key) => key !== itemKey) : [];
  const rows = Array.isArray(item) ? item : [];
  return (
    <Stack gap={4}>
      <MetricBadges keys={metricKeys} value={record} onPick={props.onPick} />
      {itemKey === "rows" || Array.isArray(item) ? (
        <RowsTable
          {...props}
          listKey={itemKey}
          path={[itemKey]}
          embedded={rows}
          rowProperties={props.rowProperties}
        />
      ) : isRecord(item) ? (
        <RecordTree value={item} path={[itemKey]} onPick={props.onPick} />
      ) : (
        <ValueKind value={item} onPick={props.onPick ? (path) => props.onPick?.([itemKey, ...path]) : undefined} />
      )}
    </Stack>
  );
}

function IterationsView(props: BodyProps) {
  const rows =
    isRecord(props.value) && Array.isArray(props.value.iterations) ? props.value.iterations : [];
  return (
    <Stack gap={4}>
      <MetricBadges keys={props.view?.metrics ?? []} value={props.value} onPick={props.onPick} />
      <RowsTable
        {...props}
        listKey="iterations"
        path={["iterations"]}
        embedded={rows}
        rowProperties={[]}
      />
    </Stack>
  );
}

function ContainerView(props: BodyProps) {
  const size = props.batchSize ?? readBatchOutput(props.value)?.batchSize ?? null;
  const child =
    props.batchChildId ??
    props.graph?.nodes.find((node) => node.parent === props.containerId)?.id ??
    null;
  return (
    <Stack gap={4}>
      <MetricBadges keys={props.view?.metrics ?? []} value={props.value} onPick={props.onPick} />
      <RoundTable {...props} itemKey={props.view?.item ?? "current"} batchSize={size} batchChildId={child} />
    </Stack>
  );
}

function RoundTable({
  channelId,
  jobId,
  seq,
  itemKey,
  rowProperties,
  graph,
  onPick,
  selectedRound,
  onSelectRound,
  onRoundsTotal,
  batchChildId,
  batchSize,
}: BodyProps & { itemKey: string }) {
  const t = useTranslate();
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ContainerRound[]>([]);
  const [total, setTotal] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const onTotal = useRef(onRoundsTotal);
  onTotal.current = onRoundsTotal;

  useEffect(() => {
    if (seq == null) return;
    let cancelled = false;
    setFailed(null);
    void listRounds(channelId, jobId, seq, {
      limit: ROUND_PAGE,
      offset: (page - 1) * ROUND_PAGE,
    })
      .then((body) => {
        if (cancelled) return;
        setItems(body.items);
        setTotal(body.total);
        onTotal.current?.(body.total);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setItems([]);
        setFailed(problemMessage(t, reason, t("channels.run.outputFailed")));
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, jobId, seq, page, t]);

  if (seq == null) {
    return (
      <Text size="xs" c="dimmed">
        {t("channels.run.notRecorded")}
      </Text>
    );
  }
  const currents = items.map((item) => stepField(item.step_preview, itemKey));
  const spread = itemKey === "current" && (rowProperties.length > 0 || currents.some(isRecord));
  const columns = spread ? rowColumnKeys(rowProperties, currents.filter(isRecord)) : [];
  const pageCount = pageCountOf(total, ROUND_PAGE);
  return (
    <Stack gap={4}>
      {failed ? (
        <Text size="xs" c="red" role="alert">
          {failed}
        </Text>
      ) : null}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t("channels.run.column.round")}</Table.Th>
            {itemKey === "rows" ? (
              <>
                <Table.Th>
                  <button type="button" className="channel-view-pick" onClick={() => onPick?.(["rows"])}>
                    _ord
                  </button>
                </Table.Th>
                <Table.Th>
                  <button type="button" className="channel-view-pick" onClick={() => onPick?.(["rows"])}>
                    {t("channels.view.metric.count")}
                  </button>
                </Table.Th>
              </>
            ) : spread ? (
              columns.map((column) => (
                <Table.Th key={column}>
                  <button
                    type="button"
                    className="channel-view-pick"
                    onClick={() => onPick?.(["current", column])}
                  >
                    {column}
                  </button>
                </Table.Th>
              ))
            ) : (
              <Table.Th>
                <button type="button" className="channel-view-pick" onClick={() => onPick?.(["current"])}>
                  {t("channels.run.column.value")}
                </button>
              </Table.Th>
            )}
            <Table.Th>{t("channels.run.roundStatus")}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((item) => {
            const failedRound = (item.status_counts.failed ?? 0) > 0;
            const selected = selectedRound === item.round;
            const step = isRecord(item.step_preview) ? item.step_preview : null;
            const current = step ? step.current : undefined;
            return (
              <Table.Tr
                key={item.round}
                data-round={item.round}
                data-failed={failedRound ? "true" : "false"}
                aria-selected={selected}
                className={[
                  "channel-view-round",
                  failedRound ? "channel-view-round--failed" : "",
                  selected ? "channel-view-round--selected" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => onSelectRound?.(item.round)}
              >
                <Table.Td>{item.round + 1}</Table.Td>
                {itemKey === "rows" ? (
                  <BatchCells
                    step={step}
                    totals={item.step_totals}
                    batchSize={batchSize}
                    expanded={expanded === item.round}
                    onToggle={() => setExpanded((currentRound) => (currentRound === item.round ? null : item.round))}
                  />
                ) : spread ? (
                  columns.map((column) => (
                    <Table.Td key={column}>
                      <button
                        type="button"
                        className="channel-view-pick"
                        onClick={() => onPick?.(["current", column])}
                      >
                        {scalarText(isRecord(current) ? current[column] : undefined)}
                      </button>
                    </Table.Td>
                  ))
                ) : (
                  <Table.Td>
                    <button type="button" className="channel-view-pick" onClick={() => onPick?.(["current"])}>
                      {scalarText(current)}
                    </button>
                  </Table.Td>
                )}
                <Table.Td>{statusText(t, item.status_counts)}</Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {items.map((item) =>
        itemKey === "rows" && expanded === item.round ? (
          <BatchExpansion
            key={`rows-${item.round}`}
            channelId={channelId}
            jobId={jobId}
            seq={seq}
            graph={graph}
            round={item}
            batchChildId={batchChildId}
            onPick={onPick}
          />
        ) : null,
      )}
      {pageCount > 1 ? <Pagination value={page} onChange={setPage} total={pageCount} size="xs" /> : null}
    </Stack>
  );
}

function BatchCells({
  step,
  totals,
  batchSize,
  expanded,
  onToggle,
}: {
  step: Record<string, unknown> | null;
  totals: Record<string, number>;
  batchSize: number | null;
  expanded: boolean;
  onToggle: () => void;
}) {
  const t = useTranslate();
  const figures = batchFigures(step, totals, batchSize);
  return (
    <>
      <Table.Td>
        {figures.from != null && figures.to != null
          ? t("channels.run.ordRange", { from: figures.from, to: figures.to })
          : ""}
      </Table.Td>
      <Table.Td>
        <button type="button" className="channel-view-pick" aria-expanded={expanded} onClick={onToggle}>
          {t("channels.run.batchRowCount", { count: figures.count })}
        </button>
      </Table.Td>
    </>
  );
}

function BatchExpansion({
  channelId,
  jobId,
  seq,
  graph,
  round,
  batchChildId,
  onPick,
}: {
  channelId: string;
  jobId: string;
  seq: number;
  graph: Graph | null;
  round: ContainerRound;
  batchChildId: string | null;
  onPick?: OutputPick;
}) {
  const rows = isRecord(round.step_preview) && Array.isArray(round.step_preview.rows) ? round.step_preview.rows : [];
  if (batchChildId && graph) {
    return (
      <BatchRoundRows
        channelId={channelId}
        jobId={jobId}
        graph={graph}
        execution={{
          seq: 0,
          node_id: batchChildId,
          container_seq: seq,
          round: round.round,
          status: "succeeded",
          started_at: null,
          finished_at: null,
          output_bytes: 0,
          output_preview: null,
          output_truncated: false,
          preview_only: false,
          preview_totals: {},
          error_code: null,
          error_message: null,
          error_detail: null,
        }}
      />
    );
  }
  return (
    <RowsTable
      channelId={channelId}
      jobId={jobId}
      value={round.step_preview}
      view={null}
      error={null}
      truncated={round.step_truncated}
      totals={round.step_totals}
      previewOnly={false}
      seq={null}
      onPick={onPick}
      rowProperties={[]}
      graph={null}
      stepItem={null}
      iterations={false}
      metricsOnly={false}
      selectedRound={null}
      batchChildId={null}
      batchSize={null}
      containerId={null}
      listKey="rows"
      path={["rows"]}
      embedded={rows}
    />
  );
}

/**
 * `_ord` bounds come only from the recorded batch size and the step's `total`.
 * Filling either from the preview length labels a different window.
 */
function batchFigures(
  step: Record<string, unknown> | null,
  totals: Record<string, number>,
  batchSize: number | null,
): { from: number | null; to: number | null; count: number } {
  const rows = step && Array.isArray(step.rows) ? step.rows : [];
  const count = totals.rows ?? rows.length;
  const total = step && typeof step.total === "number" ? step.total : null;
  if (!step || typeof step.index !== "number" || batchSize == null || batchSize < 1 || total == null) {
    return { from: null, to: null, count };
  }
  const window = batchOrdWindow(step.index, batchSize, total);
  return { from: window.afterOrd + 1, to: window.endOrd, count };
}

function statusText(t: (key: string, options?: Record<string, unknown>) => string, counts: Record<string, number>): string {
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([name, count]) => {
      const key = `channels.editor.status.${name}`;
      const label = t(key);
      return `${label === key ? name : label} ${count}`;
    });
  return parts.join(", ");
}

function stepField(step: unknown, key: string): unknown {
  return isRecord(step) ? step[key] : undefined;
}

function omitKeys(value: unknown, keys: readonly string[]): unknown {
  if (!isRecord(value) || keys.length === 0) return value;
  const next = { ...value };
  for (const key of keys) delete next[key];
  return next;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function scalarText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
