"use client";

import { Button, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentNodeStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { listExecutions } from "@/features/channels/api";
import { BatchRoundRows } from "@/features/channels/BatchRoundRows";
import { nodeDisplayName } from "@/features/channels/formatRunSubject";
import { RunErrorText } from "@/features/channels/RunErrorText";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import type { Graph, NodeExecution, NodeTypeSpec } from "@/features/channels/types";
import { successRequestId } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";

const PAGE_SIZE = 50;

function shownRound(round: number | null): string {
  if (round == null) return "";
  return String(round + 1);
}

export function RunExecutionBrowser({
  channelId,
  jobId,
  graph,
  catalog = [],
  reloadToken = 0,
  selectionRequest = null,
  onExecutionSelect,
}: {
  channelId: string;
  jobId: string;
  graph: Graph;
  catalog?: readonly NodeTypeSpec[];
  /** Parent bump. Reloads the current page without moving the page index. */
  reloadToken?: number;
  /** Move to the page that contains this seq, select it, and scroll it into view. */
  selectionRequest?: { seq: number; token: number } | null;
  /** The operator chose this row. The parent opens that node. */
  onExecutionSelect?: (execution: NodeExecution) => void;
}) {
  const t = useTranslate();
  const tRef = useRef(t);
  tRef.current = t;
  const retryRef = useRef(() => {});
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<NodeExecution[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<unknown>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [scrollTick, setScrollTick] = useState(0);
  const appliedSelection = useRef<number | null>(null);
  const pendingScroll = useRef<number | null>(null);
  const selectedRowRef = useRef<HTMLButtonElement | null>(null);
  const seenReload = useRef(reloadToken);
  const seenRetry = useRef(retryToken);
  retryRef.current = () => setRetryToken((token) => token + 1);

  useEffect(() => {
    let cancelled = false;
    const reloadAtStart = reloadToken;
    const retryAtStart = retryToken;
    const reconcileSelection =
      seenReload.current !== reloadAtStart || seenRetry.current !== retryAtStart;
    setLoading(true);
    void listExecutions(channelId, jobId, {
      limit: PAGE_SIZE,
      offset: pageToOffset(page, PAGE_SIZE),
    })
      .then((body) => {
        if (cancelled) return;
        setItems(body.items);
        setTotal(body.total);
        setRequestId(successRequestId(body));
        setFailure(null);
        if (!reconcileSelection) return;
        setSelected((current) =>
          body.items.some((item) => item.seq === current) ? current : null,
        );
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setFailure(reason);
        presentProblemNotification(tRef.current, reason, {
          onRetry: () => retryRef.current(),
        });
      })
      .finally(() => {
        if (cancelled) return;
        // Strict Mode runs this effect twice. Recording the token here, after the
        // fetch settles, keeps the second run able to clear a missing seq.
        seenReload.current = reloadAtStart;
        seenRetry.current = retryAtStart;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, jobId, page, reloadToken, retryToken]);

  useEffect(() => {
    if (!selectionRequest) return;
    if (appliedSelection.current === selectionRequest.token) return;
    appliedSelection.current = selectionRequest.token;
    pendingScroll.current = selectionRequest.seq;
    const nextPage = Math.floor((selectionRequest.seq - 1) / PAGE_SIZE) + 1;
    setSelected(selectionRequest.seq);
    setPage(nextPage);
    setScrollTick((tick) => tick + 1);
  }, [selectionRequest]);

  useEffect(() => {
    const seq = pendingScroll.current;
    if (seq == null || loading) return;
    if (!items.some((item) => item.seq === seq)) return;
    selectedRowRef.current?.closest("tr")?.scrollIntoView({ block: "nearest" });
    pendingScroll.current = null;
  }, [items, loading, scrollTick, selected]);

  const current = items.find((item) => item.seq === selected) ?? null;
  const list = {
    presentation: listPresentationOf({
      loading,
      error: failure != null && items.length === 0 ? "unloaded" : null,
      total,
      itemCount: items.length,
      filtered: false,
    }),
    error: null,
    errorRequestId: null,
    reload: () => retryRef.current(),
    page,
    setPage,
    pageSize: PAGE_SIZE,
    total,
  };
  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>
        {t("channels.run.executionList")}
      </Text>
      <ListTable
        embedded
        list={list}
        columnCount={7}
        minWidth={840}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.run.column.node")}</Table.Th>
            <Table.Th>{t("channels.run.column.status")}</Table.Th>
            <Table.Th>{t("channels.runs.started")}</Table.Th>
            <Table.Th>{t("channels.run.column.executionRound")}</Table.Th>
            <Table.Th>{t("channels.run.column.duration")}</Table.Th>
            <Table.Th>{t("channels.run.column.outputBytes")}</Table.Th>
            <Table.Th>{t("channels.run.column.error")}</Table.Th>
          </Table.Tr>
        }
      >
        {items.map((item) => {
          const label = nodeDisplayName(graph.nodes, item.node_id);
          const named = label != null && label !== item.node_id;
          return (
            <Table.Tr key={item.seq}>
              <Table.Td>
                <Button
                  ref={item.seq === selected ? selectedRowRef : undefined}
                  variant={item.seq === selected ? "light" : "subtle"}
                  size="compact-sm"
                  onClick={() => {
                    setSelected(item.seq);
                    onExecutionSelect?.(item);
                  }}
                >
                  {named && label ? label : item.node_id}
                </Button>
              </Table.Td>
              <Table.Td>
                <StatusBadge
                  size="xs"
                  tone={presentNodeStatus(item.status).tone}
                  labelKey={presentNodeStatus(item.status).labelKey}
                />
              </Table.Td>
              <Table.Td>
                <Instant value={item.started_at} requestId={requestId} />
              </Table.Td>
              <Table.Td>{shownRound(item.round)}</Table.Td>
              <Table.Td>{formatJobDuration(item)}</Table.Td>
              <Table.Td>{item.output_bytes}</Table.Td>
              <Table.Td>
                <RunErrorText code={item.error_code} message={item.error_message} />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
      {current ? (
        <Stack gap={4}>
          <RunExecutionOutput
            channelId={channelId}
            jobId={jobId}
            item={current}
            graph={graph}
            view={
              catalog.find(
                (spec) =>
                  spec.type === graph.nodes.find((node) => node.id === current.node_id)?.type,
              )?.output_view ?? null
            }
          />
          <BatchRoundRows
            channelId={channelId}
            jobId={jobId}
            graph={graph}
            execution={current}
          />
        </Stack>
      ) : null}
    </Stack>
  );
}
