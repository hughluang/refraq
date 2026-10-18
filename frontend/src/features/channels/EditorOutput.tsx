"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { presentNodeStatus } from "@/components/display/statusTone";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { canPinNode } from "@/features/channels/editorSession";
import { NodeRegion } from "@/features/channels/NodeRegion";
import { RunExecutionOutput } from "@/features/channels/RunExecutionOutput";
import type { ChannelRunDetail, NodeExecution } from "@/features/channels/types";

type Props = {
  channelId: string;
  nodeId: string;
  nodeType: string;
  result: ChannelRunDetail | null;
  busy: boolean;
  error: string | null;
  problemTexts: readonly string[];
  recordName: string;
  pinned: boolean;
  canCancel: boolean;
  onTest: (nodeId: string) => void;
  onCancel: () => void | Promise<unknown>;
  onPin: (nodeId: string, output: unknown) => void;
  onUnpin: (nodeId: string) => void;
};

export function EditorOutputRegion({
  channelId,
  nodeId,
  nodeType,
  result,
  busy,
  error,
  problemTexts,
  recordName,
  pinned,
  canCancel,
  onTest,
  onCancel,
  onPin,
  onUnpin,
}: Props) {
  const t = useTranslate();
  const cancel = useConsoleMutation();
  const name = recordName.trim() || nodeId;
  const mine = (result?.node_executions ?? [])
    .filter((item) => item.node_id === nodeId)
    .slice()
    .sort((left, right) => left.seq - right.seq);
  const latest = mine.length > 0 ? mine[mine.length - 1] : null;
  const allowPin = canPinNode(nodeType) && latest != null;

  let body;
  if (busy && result == null) {
    body = (
      <Text size="sm" c="dimmed">
        {t("channels.editor.testing")}
      </Text>
    );
  } else if (error && result == null) {
    body = null;
  } else if (result == null) {
    body = (
      <Text size="sm" c="dimmed">
        {t("channels.editor.idle")}
      </Text>
    );
  } else if (mine.length === 0 && busy) {
    body = (
      <Text size="sm" c="dimmed">
        {t("channels.editor.testing")}
      </Text>
    );
  } else if (mine.length === 0) {
    body = (
      <Text size="sm" c="dimmed">
        {t("channels.editor.notReached")}
      </Text>
    );
  } else {
    body = (
      <Stack gap="sm">
        {mine.length > 1 ? (
          <Text size="xs" c="dimmed">
            {t("channels.run.executions", { count: mine.length })}
          </Text>
        ) : null}
        {mine.map((item) => (
          <ExecutionBlock
            key={item.seq}
            channelId={channelId}
            jobId={result.run.job_id}
            item={item}
            many={mine.length > 1}
          />
        ))}
        {allowPin ? (
          <Button
            size="compact-xs"
            variant={pinned ? "filled" : "default"}
            onClick={() => {
              if (pinned) onUnpin(nodeId);
              else if (latest) onPin(nodeId, latest.output_preview);
            }}
          >
            {pinned ? t("channels.editor.unpin") : t("channels.editor.pin")}
          </Button>
        ) : null}
      </Stack>
    );
  }

  return (
    <NodeRegion
      title={t("channels.editor.region")}
      tone="run"
      action={
        busy ? (
          <Button
            size="compact-xs"
            color="red"
            variant="light"
            disabled={!canCancel}
            loading={cancel.submitting}
            onClick={() => {
              cancel.run({
                safety: "confirm",
                recordName: name,
                title: t("channels.editor.cancel.confirmTitle", { name }),
                consequence: t("channels.editor.cancel.consequence"),
                confirmLabel: t("channels.editor.cancel.confirm"),
                confirmColor: "red",
                outcome: t("channels.editor.cancel.outcome"),
                execute: () => Promise.resolve(onCancel()),
              });
            }}
          >
            {t("common.cancel")}
          </Button>
        ) : (
          <Button size="compact-xs" variant="light" onClick={() => onTest(nodeId)}>
            {t("channels.editor.test")}
          </Button>
        )
      }
    >
      {cancel.dialog}
      <Stack gap="sm">
        <Text size="xs" c="dimmed">
          {t("channels.editor.hint")}
        </Text>
        {error ? (
          <Text role="alert" size="sm" c="red">
            {error}
          </Text>
        ) : null}
        {problemTexts.map((text) => (
          <Text key={text} size="sm" c="red">
            {text}
          </Text>
        ))}
        {body}
      </Stack>
    </NodeRegion>
  );
}

function ExecutionBlock({
  channelId,
  jobId,
  item,
  many,
}: {
  channelId: string;
  jobId: string;
  item: NodeExecution;
  many: boolean;
}) {
  const t = useTranslate();
  return (
    <Stack gap={4}>
      {many ? (
        <Text size="xs" fw={600}>
          {t("channels.run.execution", { seq: item.seq })}
        </Text>
      ) : null}
      <Text size="xs" fw={600}>
        {statusLabel(t, item.status)}
      </Text>
      <RunExecutionOutput channelId={channelId} jobId={jobId} item={item} />
    </Stack>
  );
}

function statusLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  status: string,
): string {
  return t(presentNodeStatus(status).labelKey);
}
