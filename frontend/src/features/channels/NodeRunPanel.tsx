"use client";

import { Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { ancestorIds, executionScope } from "@/features/channels/runSession";
import type { ChannelRunDetail, GraphNode } from "@/features/channels/types";

type Props = {
  nodeId: string;
  nodes: readonly Pick<GraphNode, "id" | "name" | "ref">[];
  detail: ChannelRunDetail;
};

function previewText(value: unknown): string {
  const encoded = JSON.stringify(value, null, 2);
  return typeof encoded === "string" ? encoded : "";
}

export function NodeRunPanel({ nodeId, nodes, detail }: Props) {
  const t = useTranslate();
  const graph = detail.graph;
  const names = new Map(nodes.map((node) => [node.id, node.name || node.ref || node.id]));
  const scope = graph ? executionScope(graph, detail.run.stop_at_node_id ?? null) : null;
  const ancestors = ancestorIds(nodeId, graph?.edges ?? []);
  const mine = detail.node_executions.find((item) => item.node_id === nodeId) ?? null;
  const upstream = detail.node_executions
    .filter((item) => ancestors.has(item.node_id))
    .slice()
    .sort((left, right) => left.seq - right.seq);
  const absent = scope != null && !scope.has(nodeId);

  return (
    <Stack gap="sm">
      {absent ? <Text size="sm">{t("channels.run.absent")}</Text> : null}
      <Text size="sm" fw={600}>
        {t("channels.run.upstream")}
      </Text>
      {upstream.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("channels.run.empty")}
        </Text>
      ) : (
        upstream.map((item) => (
          <Stack key={item.seq} gap={4}>
            <Text size="xs" fw={600}>
              {names.get(item.node_id) ?? item.node_id}
            </Text>
            {item.error_message ? (
              <Text size="xs" c="red">
                {item.error_message}
              </Text>
            ) : (
              <Code block>{previewText(item.output_preview)}</Code>
            )}
          </Stack>
        ))
      )}
      <Text size="sm" fw={600}>
        {t("channels.run.result")}
      </Text>
      {mine == null ? (
        absent ? null : (
          <Text size="sm" c="dimmed">
            {t("channels.run.waiting")}
          </Text>
        )
      ) : mine.error_message ? (
        <Text size="sm" c="red">
          {mine.error_message}
        </Text>
      ) : (
        <Code block>{previewText(mine.output_preview)}</Code>
      )}
    </Stack>
  );
}
