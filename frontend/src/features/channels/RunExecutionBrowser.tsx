"use client";

import { Button, Group, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentNodeStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { listExecutions } from "@/features/channels/api";
import { nodeDisplayName } from "@/features/channels/formatRunSubject";
import { RunErrorText } from "@/features/channels/RunErrorText";
import type { Graph, NodeExecution } from "@/features/channels/types";
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
  reloadToken = 0,
  selectionRequest = null,
  onExecutionSelect,
  collapsed = false,
  onToggleCollapsed,
}: {
  channelId: string;
  jobId: string;
  graph: Graph;
  /** Parent bump. Reloads the current page without moving the page index. */
  reloadToken?: number;
  /** Move to the page that contains this seq, select it, and scroll it into view. */
  selectionRequest?: { seq: number; token: number } | null;
  /** The operator chose this row. The parent opens that node. */
  onExecutionSelect?: (execution: NodeExecution) => void;
  /** Hide the table. Selection stays so opening the index again shows the same row. */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
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
    if (seq == null || loading || collapsed) return;
    if (!items.some((item) => item.seq === seq)) return;
    selectedRowRef.current?.closest("tr")?.scrollIntoView({ block: "nearest" });
    pendingScroll.current = null;
  }, [collapsed, items, loading, scrollTick, selected]);

  const wasCollapsed = useRef(collapsed);
  useEffect(() => {
    const opened = wasCollapsed.current && !collapsed;
    wasCollapsed.current = collapsed;
    if (!opened || loading || selected == null) return;
    selectedRowRef.current?.closest("tr")?.scrollIntoView({ block: "nearest" });
  }, [collapsed, items, loading, selected]);

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
    <Stack gap="sm" flex={collapsed ? undefined : 1} mih={collapsed ? undefined : 0} h={collapsed ? undefined : "100%"}>
      <Group justify="space-between" wrap="nowrap" gap="xs">
        <Text size="sm" fw={600}>
          {t("channels.run.executionList")}
        </Text>
        {onToggleCollapsed ? (
          <Button
            type="button"
            variant="subtle"
            size="compact-xs"
            aria-expanded={!collapsed}
            onClick={onToggleCollapsed}
          >
            {t(collapsed ? "channels.run.executionList.show" : "channels.run.executionList.hide")}
          </Button>
        ) : null}
      </Group>
      {collapsed ? null : (
      <ListTable
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
                  aria-pressed={item.seq === selected}
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
      )}
    </Stack>
  );
}
