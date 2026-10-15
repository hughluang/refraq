"use client";

import { Button, Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { NumberField } from "@/components/form/NumberField";
import {
  EDITOR_ROW_LIMIT_MAX,
  EDITOR_ROW_LIMIT_MIN,
  canPinNode,
  dryRunSummary,
  type DryRunSummary,
} from "@/features/channels/editorSession";
import { NodeRegion } from "@/features/channels/NodeRegion";
import { RunErrorText } from "@/features/channels/RunErrorText";
import type { EditorExecution, EditorNodeExecution } from "@/features/channels/types";

type Props = {
  nodeId: string;
  nodeType: string;
  result: EditorExecution | null;
  busy: boolean;
  error: string | null;
  problemTexts: readonly string[];
  pinned: boolean;
  rowLimit: number | string;
  onRowLimit: (value: number | string) => void;
  onTest: (nodeId: string) => void;
  onPin: (nodeId: string, output: unknown) => void;
  onUnpin: (nodeId: string) => void;
};

export function EditorOutputRegion({
  nodeId,
  nodeType,
  result,
  busy,
  error,
  problemTexts,
  pinned,
  rowLimit,
  onRowLimit,
  onTest,
  onPin,
  onUnpin,
}: Props) {
  const t = useTranslate();
  const mine = (result?.node_executions ?? [])
    .filter((item) => item.node_id === nodeId)
    .slice()
    .sort((left, right) => left.seq - right.seq);
  const latest = mine.length > 0 ? mine[mine.length - 1] : null;
  const allowPin = canPinNode(nodeType) && latest != null;

  let body;
  if (busy) {
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
          <ExecutionBlock key={item.seq} item={item} nodeType={nodeType} many={mine.length > 1} />
        ))}
        {allowPin ? (
          <Button
            size="compact-xs"
            variant={pinned ? "filled" : "default"}
            onClick={() => {
              if (pinned) onUnpin(nodeId);
              else if (latest) onPin(nodeId, latest.output);
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
        <Button
          size="compact-xs"
          variant="light"
          loading={busy}
          disabled={busy}
          onClick={() => onTest(nodeId)}
        >
          {t("channels.editor.test")}
        </Button>
      }
    >
      <Stack gap="sm">
        <Text size="xs" c="dimmed">
          {t("channels.editor.hint")}
        </Text>
        <NumberField
          editable={!busy}
          label={t("channels.editor.rowLimit")}
          description={t("channels.editor.rowLimitHint")}
          min={EDITOR_ROW_LIMIT_MIN}
          max={EDITOR_ROW_LIMIT_MAX}
          w={180}
          value={rowLimit}
          onChange={onRowLimit}
        />
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
  item,
  nodeType,
  many,
}: {
  item: EditorNodeExecution;
  nodeType: string;
  many: boolean;
}) {
  const t = useTranslate();
  const failed = item.status === "failed" || item.error_message != null;
  const summary = dryRunSummary(nodeType, item.output);
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
      {failed ? (
        <Text size="xs" c="red">
          <RunErrorText code={item.error_code} message={item.error_message} />
        </Text>
      ) : null}
      {summary ? <DryRunNotice summary={summary} /> : null}
      {item.truncated ? (
        <Text size="xs">{t("channels.editor.truncated")}</Text>
      ) : null}
      <Code block>{JSON.stringify(item.output, null, 2)}</Code>
    </Stack>
  );
}

function DryRunNotice({ summary }: { summary: DryRunSummary }) {
  const t = useTranslate();
  const lines =
    summary.kind === "state.variable"
      ? [
          t("channels.editor.counts.applied", {
            applied: t(`channels.editor.applied.${summary.applied}`),
          }),
        ]
      : (
          [
            ["inserted", summary.inserted],
            ["updated", summary.updated],
            ["unchanged", summary.unchanged],
            ["deleted", summary.deleted],
            ["unmatched", summary.unmatched],
          ] as const
        ).map(([key, count]) => t(`channels.editor.counts.${key}`, { count }));
  return (
    <Stack gap={2}>
      <Text size="sm" fw={600}>
        {t("channels.editor.dryRun")}
      </Text>
      {lines.map((line) => (
        <Text key={line} size="sm">
          {line}
        </Text>
      ))}
    </Stack>
  );
}

function statusLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  status: string,
): string {
  const key = `channels.editor.status.${status}`;
  const text = t(key);
  return text === key ? status : text;
}
