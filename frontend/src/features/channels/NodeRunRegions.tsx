"use client";

import { Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { NodeRegion } from "@/features/channels/NodeRegion";
import { RunErrorText } from "@/features/channels/RunErrorText";
import {
  ancestorIds,
  executionScope,
  isTerminalRun,
} from "@/features/channels/runSession";
import type { ChannelRunDetail, GraphNode, NodeExecution } from "@/features/channels/types";

type NodeInfo = Pick<GraphNode, "id" | "name" | "ref">;

function previewText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function ExecutionOutput({ item }: { item: NodeExecution }) {
  if (item.status === "failed" || item.error_message) {
    return (
      <Text size="xs" c="red">
        <RunErrorText code={item.error_code} message={item.error_message} />
      </Text>
    );
  }
  return <Code block>{previewText(item.output_preview)}</Code>;
}

export function UpstreamRegion({
  nodeId,
  nodes,
  hasUpstream,
  detail,
}: {
  nodeId: string;
  nodes: readonly NodeInfo[];
  /** Whether the node has an incoming edge on the canvas, independent of any run. */
  hasUpstream: boolean;
  detail: ChannelRunDetail | null;
}) {
  const t = useTranslate();
  const info = new Map(nodes.map((node) => [node.id, node]));
  let body;
  if (!hasUpstream) {
    body = t("channels.run.noUpstream");
  } else if (detail == null) {
    body = t("channels.run.idle");
  } else {
    const ancestors = ancestorIds(nodeId, detail.graph?.edges ?? []);
    const items = detail.node_executions
      .filter((item) => ancestors.has(item.node_id))
      .slice()
      .sort((left, right) => left.seq - right.seq);
    body =
      items.length === 0 ? (
        t("channels.run.empty")
      ) : (
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
                <ExecutionOutput item={item} />
              </Stack>
            );
          })}
        </Stack>
      );
  }
  return (
    <NodeRegion title={t("channels.run.upstream")} tone="run">
      {typeof body === "string" ? (
        <Text size="sm" c="dimmed">
          {body}
        </Text>
      ) : (
        body
      )}
    </NodeRegion>
  );
}

export function ResultRegion({
  nodeId,
  detail,
}: {
  nodeId: string;
  detail: ChannelRunDetail | null;
}) {
  const t = useTranslate();
  let body;
  if (detail == null) {
    body = t("channels.run.idle");
  } else {
    const scope = detail.graph
      ? executionScope(detail.graph, detail.run.stop_at_node_id ?? null)
      : null;
    const mine = detail.node_executions
      .filter((item) => item.node_id === nodeId)
      .slice()
      .sort((left, right) => left.seq - right.seq);
    if (mine.length === 0 && scope != null && !scope.has(nodeId)) {
      body = t("channels.run.absent");
    } else if (mine.length === 0) {
      body = isTerminalRun(detail.run.status)
        ? t("channels.run.notReached")
        : t("channels.run.waiting");
    } else if (mine.length === 1 && mine[0]?.status === "running") {
      body = t("channels.run.running");
    } else if (mine.length === 1 && mine[0]) {
      body = <ExecutionOutput item={mine[0]} />;
    } else {
      body = (
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
                <ExecutionOutput item={item} />
              )}
            </Stack>
          ))}
        </Stack>
      );
    }
  }
  return (
    <NodeRegion title={t("channels.run.result")} tone="run">
      {typeof body === "string" ? (
        <Text size="sm" c="dimmed">
          {body}
        </Text>
      ) : (
        body
      )}
    </NodeRegion>
  );
}
