"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ListPager } from "@/components/display/ListPager";
import { listExecutions } from "@/features/channels/api";
import { NodeRegion } from "@/features/channels/NodeRegion";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import { ancestorIds } from "@/features/channels/runSession";
import type { ChannelRunDetail, GraphNode, NodeExecution } from "@/features/channels/types";
import { pageToOffset } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";

type NodeInfo = Pick<GraphNode, "id" | "name" | "ref">;
type Translate = (key: string, options?: Record<string, unknown>) => string;

const EXECUTION_PAGE = 50;

function useNodeExecutions(
  channelId: string,
  jobId: string | null,
  nodeId: string,
  count: number,
) {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<NodeExecution[] | null>(null);
  const [total, setTotal] = useState(0);
  const [failure, setFailure] = useState<unknown>(null);
  useEffect(() => {
    if (!channelId || !jobId || count <= 0) {
      setItems([]);
      setTotal(0);
      setFailure(null);
      return;
    }
    let cancelled = false;
    setItems(null);
    setFailure(null);
    void listExecutions(channelId, jobId, {
      node_id: nodeId,
      limit: EXECUTION_PAGE,
      offset: pageToOffset(page, EXECUTION_PAGE),
    })
      .then((body) => {
        if (cancelled) return;
        setItems(body.items);
        setTotal(body.total);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setItems([]);
        setFailure(reason);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, jobId, nodeId, count, page]);
  return { page, setPage, items, total, failure };
}

function summaryCount(detail: ChannelRunDetail | null, nodeId: string): number {
  return detail?.node_summaries.find((item) => item.node_id === nodeId)?.execution_count ?? 0;
}

/** Existing empty-state sentence, or null when the region would show output. */
function upstreamSentence(
  t: Translate,
  hasUpstream: boolean,
  detail: ChannelRunDetail | null,
  loaded: boolean,
  count: number,
  error: string | null,
): string | null {
  if (!hasUpstream) return t("channels.run.noUpstream");
  if (detail == null) return t("channels.run.idle");
  if (error) return error;
  if (!loaded) return null;
  if (count === 0) return t("channels.run.empty");
  return null;
}

/** Existing empty-state sentence, or null when the region would show output. */
function resultSentence(
  t: Translate,
  detail: ChannelRunDetail | null,
  count: number,
  items: readonly NodeExecution[] | null,
  error: string | null,
): string | null {
  if (detail == null) return t("channels.run.idle");
  if (count === 0) return t("channels.run.absent");
  if (error) return error;
  if (items == null) return null;
  if (count === 1 && items.length === 1 && items[0]?.status === "running") {
    return t("channels.run.running");
  }
  return null;
}

export function UpstreamRegion({
  channelId,
  nodeId,
  nodes,
  hasUpstream,
  detail,
}: {
  channelId: string;
  nodeId: string;
  nodes: readonly NodeInfo[];
  /** Whether the node has an incoming edge on the canvas, independent of any run. */
  hasUpstream: boolean;
  detail: ChannelRunDetail | null;
}) {
  const t = useTranslate();
  const ancestors = ancestorIds(nodeId, detail?.graph?.edges ?? [], detail?.graph?.nodes ?? []);
  const ancestorList = [...ancestors];
  const [items, setItems] = useState<NodeExecution[] | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const jobId = detail?.run.job_id ?? null;
  const summaryKey = detail?.node_summaries
    .filter((item) => ancestors.has(item.node_id) && item.execution_count > 0)
    .map((item) => `${item.node_id}:${item.execution_count}`)
    .join("|");
  useEffect(() => {
    if (!detail || !channelId || !jobId) {
      setItems([]);
      setFailure(null);
      return;
    }
    const targets = detail.node_summaries.filter(
      (item) => ancestors.has(item.node_id) && item.execution_count > 0,
    );
    if (targets.length === 0) {
      setItems([]);
      setFailure(null);
      return;
    }
    let cancelled = false;
    setItems(null);
    setFailure(null);
    void Promise.all(
      targets.map((summary) =>
        listExecutions(channelId, jobId, {
          node_id: summary.node_id,
          limit: EXECUTION_PAGE,
          offset: 0,
        }),
      ),
    )
      .then((pages) => {
        if (cancelled) return;
        const merged = pages.flatMap((page) => page.items);
        merged.sort((left, right) => left.seq - right.seq);
        setItems(merged);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setItems([]);
        setFailure(reason);
      });
    return () => {
      cancelled = true;
    };
  }, [detail, channelId, jobId, summaryKey, ancestorList.join("|")]);
  const loaded = items != null;
  const errorText =
    failure == null ? null : problemMessage(t, failure, t("channels.run.outputFailed"));
  const sentence = upstreamSentence(
    t,
    hasUpstream,
    detail,
    loaded,
    items?.length ?? 0,
    errorText,
  );
  if (sentence == null && detail != null && items != null && items.length > 0) {
    const info = new Map(nodes.map((node) => [node.id, node]));
    return (
      <NodeRegion title={t("channels.run.upstream")} tone="run">
        <Stack gap="sm">
          {items.map((item) => {
            const node = info.get(item.node_id);
            return (
              <Stack key={item.seq} gap={4}>
                <Text size="xs" fw={600}>
                  {node?.name || node?.ref || item.node_id}
                </Text>
                {node?.ref ? (
                  <Text size="xs" c="dimmed">
                    {`self.${node.ref}.output`}
                  </Text>
                ) : null}
                <RunExecutionOutput
                  channelId={channelId}
                  jobId={detail.run.job_id}
                  item={item}
                />
              </Stack>
            );
          })}
        </Stack>
      </NodeRegion>
    );
  }
  return (
    <NodeRegion title={t("channels.run.upstream")} tone="run">
      <Text size="sm" c="dimmed">
        {sentence}
      </Text>
    </NodeRegion>
  );
}

export function ResultRegion({
  channelId,
  nodeId,
  detail,
}: {
  channelId: string;
  nodeId: string;
  detail: ChannelRunDetail | null;
}) {
  const t = useTranslate();
  const count = summaryCount(detail, nodeId);
  const page = useNodeExecutions(channelId, detail?.run.job_id ?? null, nodeId, count);
  const errorText =
    page.failure == null ? null : problemMessage(t, page.failure, t("channels.run.outputFailed"));
  const sentence = resultSentence(t, detail, count, page.items, errorText);
  if (sentence == null && detail != null && page.items != null && page.items.length > 0) {
    const only = count === 1 ? page.items[0] : undefined;
    return (
      <NodeRegion title={t("channels.run.result")} tone="run">
        {only ? (
          <RunExecutionOutput channelId={channelId} jobId={detail.run.job_id} item={only} />
        ) : (
          <Stack gap="sm">
            <Text size="xs" c="dimmed">
              {t("channels.run.executions", { count })}
            </Text>
            {page.items.map((item) => (
              <Stack key={item.seq} gap={4}>
                <Text size="xs" fw={600}>
                  {t("channels.run.execution", { seq: item.seq })}
                </Text>
                {item.status === "running" ? (
                  <Text size="sm" c="dimmed">
                    {t("channels.run.running")}
                  </Text>
                ) : (
                  <RunExecutionOutput channelId={channelId} jobId={detail.run.job_id} item={item} />
                )}
              </Stack>
            ))}
            <ListPager
              page={page.page}
              pageSize={EXECUTION_PAGE}
              total={page.total}
              onChange={page.setPage}
            />
          </Stack>
        )}
      </NodeRegion>
    );
  }
  return (
    <NodeRegion title={t("channels.run.result")} tone="run">
      <Text size="sm" c="dimmed">
        {sentence}
      </Text>
    </NodeRegion>
  );
}
