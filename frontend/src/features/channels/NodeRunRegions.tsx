"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { NodeRegion } from "@/features/channels/NodeRegion";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import { ancestorIds } from "@/features/channels/runSession";
import type { ChannelRunDetail, GraphNode, NodeExecution } from "@/features/channels/types";

type NodeInfo = Pick<GraphNode, "id" | "name" | "ref">;
type Translate = (key: string, options?: Record<string, unknown>) => string;

function ancestorExecutions(nodeId: string, detail: ChannelRunDetail): NodeExecution[] {
  const ancestors = ancestorIds(nodeId, detail.graph?.edges ?? [], detail.graph?.nodes ?? []);
  return detail.node_executions
    .filter((item) => ancestors.has(item.node_id))
    .slice()
    .sort((left, right) => left.seq - right.seq);
}

function ownExecutions(nodeId: string, detail: ChannelRunDetail): NodeExecution[] {
  return detail.node_executions
    .filter((item) => item.node_id === nodeId)
    .slice()
    .sort((left, right) => left.seq - right.seq);
}

/** Existing empty-state sentence, or null when the region would show output. */
function upstreamSentence(
  t: Translate,
  nodeId: string,
  hasUpstream: boolean,
  detail: ChannelRunDetail | null,
): string | null {
  if (!hasUpstream) return t("channels.run.noUpstream");
  if (detail == null) return t("channels.run.idle");
  if (ancestorExecutions(nodeId, detail).length === 0) return t("channels.run.empty");
  return null;
}

/** Existing empty-state sentence, or null when the region would show output. */
function resultSentence(
  t: Translate,
  nodeId: string,
  detail: ChannelRunDetail | null,
): string | null {
  if (detail == null) return t("channels.run.idle");
  const mine = ownExecutions(nodeId, detail);
  if (mine.length === 0) return t("channels.run.absent");
  if (mine.length === 1 && mine[0]?.status === "running") return t("channels.run.running");
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
  const sentence = upstreamSentence(t, nodeId, hasUpstream, detail);
  // A null sentence means the run has ancestor executions, so detail is present.
  if (sentence == null && detail != null) {
    const info = new Map(nodes.map((node) => [node.id, node]));
    const items = ancestorExecutions(nodeId, detail);
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
  const sentence = resultSentence(t, nodeId, detail);
  // A null sentence means this node has output to render, so detail is present.
  if (sentence == null && detail != null) {
    const mine = ownExecutions(nodeId, detail);
    const only = mine.length === 1 ? mine[0] : undefined;
    return (
      <NodeRegion title={t("channels.run.result")} tone="run">
        {only ? (
          <RunExecutionOutput channelId={channelId} jobId={detail.run.job_id} item={only} />
        ) : (
          <Stack gap="sm">
            <Text size="xs" c="dimmed">
              {t("channels.run.executions", { count: mine.length })}
            </Text>
            {mine.map((item) => (
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
