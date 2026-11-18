"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { useShowInstant } from "@/hooks/useFormatInstant";

type Times = {
  created_at: string | null;
  started_at: string | null;
  scheduled_for: string | null;
  finished_at: string | null;
};

export function JobTimes({ job, detail = false }: { job: Times; detail?: boolean }) {
  const t = useTranslate();
  const showInstant = useShowInstant();
  return (
    <Stack gap={2}>
      {detail ? <Text size="xs">{t("jobs.fields.scheduled")}: {showInstant(job.scheduled_for)}</Text> : null}
      <Text size="xs">{t("jobs.fields.created")}: {showInstant(job.created_at)}</Text>
      <Text size="xs">{t("jobs.fields.started")}: {job.started_at === null ? t("jobs.notStarted") : showInstant(job.started_at)}</Text>
      {detail ? <Text size="xs">{t("jobs.fields.finished")}: {showInstant(job.finished_at)}</Text> : null}
    </Stack>
  );
}
