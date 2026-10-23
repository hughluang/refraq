"use client";

import { Button, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentNodeStatus } from "@/components/display/statusTone";
import { listExecutions } from "@/features/channels/api";
import { BatchRoundRows } from "@/features/channels/BatchRoundRows";
import { nodeDisplayName } from "@/features/channels/formatRunSubject";
import { RunErrorText } from "@/features/channels/RunErrorText";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import type { Graph, NodeExecution } from "@/features/channels/types";
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";

const PAGE_SIZE = 50;

export function RunExecutionBrowser({
  channelId,
  jobId,
  graph,
}: {
  channelId: string;
  jobId: string;
  graph: Graph;
}) {
  const t = useTranslate();
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<NodeExecution[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void listExecutions(channelId, jobId, {
      limit: PAGE_SIZE,
      offset: pageToOffset(page, PAGE_SIZE),
    })
      .then((body) => {
        if (cancelled) return;
        setItems(body.items);
        setTotal(body.total);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(problemMessage(t, reason, t("channels.run.outputFailed")));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, jobId, page, reloadToken, t]);

  const current = items.find((item) => item.seq === selected) ?? null;
  const list = {
    presentation: listPresentationOf({
      loading,
      error,
      total,
      itemCount: items.length,
      filtered: false,
    }),
    error,
    errorRequestId: null,
    reload: () => setReloadToken((token) => token + 1),
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
        columnCount={3}
        minWidth={480}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.run.column.node")}</Table.Th>
            <Table.Th>{t("channels.run.column.status")}</Table.Th>
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
                  variant={item.seq === selected ? "light" : "subtle"}
                  size="compact-sm"
                  onClick={() => setSelected(item.seq)}
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
                <RunErrorText code={item.error_code} message={item.error_message} />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
      {current ? (
        <Stack gap={4}>
          <RunExecutionOutput channelId={channelId} jobId={jobId} item={current} />
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
