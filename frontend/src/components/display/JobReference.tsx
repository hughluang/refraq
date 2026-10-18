"use client";

import { Button, Group, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";

const KIND_LABEL: Record<string, string> = {
  structure: "jobs.kind.structure",
  join_detection: "jobs.kind.join_detection",
  catalog_embed: "jobs.kind.catalog_embed",
  entity_reconcile: "jobs.kind.entity_reconcile",
  entity_table_drop: "jobs.kind.entity_table_drop",
  entity_access_views: "jobs.kind.entity_access_views",
  channel_run: "jobs.kind.channel_run",
};

export function jobKindLabelKey(kind: string): string {
  return KIND_LABEL[kind] ?? "jobs.kind.unknown";
}

type Props = {
  jobId: string;
  kind: string;
  status?: string | null;
  onOpen: (jobId: string) => void;
};

export function JobReference({ jobId, kind, status, onOpen }: Props) {
  const t = useTranslate();
  const presentation = status ? presentJobStatus(status) : null;
  const summary = t(jobKindLabelKey(kind));
  return (
    <Button
      type="button"
      variant="subtle"
      size="compact-sm"
      px={4}
      onClick={(event) => {
        event.stopPropagation();
        onOpen(jobId);
      }}
    >
      <Group gap={6} wrap="nowrap" align="baseline">
        {presentation ? (
          <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} size="xs" />
        ) : null}
        <Text size="sm" component="span">
          {summary}
        </Text>
        <Text size="xs" c="dimmed" ff="monospace" component="span">
          {jobId}
        </Text>
      </Group>
    </Button>
  );
}
