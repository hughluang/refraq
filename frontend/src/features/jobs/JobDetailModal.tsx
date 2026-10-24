"use client";

import {
  Button,
  Code,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef } from "react";

import { jobKindLabelKey } from "@/components/display/JobReference";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StaleNotice } from "@/components/display/StaleNotice";
import { presentJobStatus } from "@/components/display/statusTone";
import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { isSessionExpiredError } from "@/lib/api";

import { getJob, getJobLogs } from "@/features/jobs/api";
import { JobCancelButton } from "@/features/jobs/JobCancelButton";
import { formatJobError } from "@/features/jobs/formatJobError";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { formatJobDuration } from "@/lib/datetime";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

type Props = {
  jobId: string | null;
  opened: boolean;
  onClose: () => void;
  onChanged?: () => void;
};

export function JobDetailModal({ jobId, opened, onClose, onChanged }: Props) {
  const formatInstant = useFormatInstant();
  const t = useTranslate();
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const live = useLiveStatus({
    enabled: opened && Boolean(jobId),
    key: opened ? jobId : null,
    fetch: async (signal) => {
      if (!jobId) throw new Error("missing job");
      const [jobRes, logsRes] = await Promise.all([
        getJob(jobId, { signal }),
        getJobLogs(jobId, { signal }),
      ]);
      return { job: jobRes.job, logs: logsRes.body };
    },
    isTerminal: (item) => TERMINAL.has(item.job.status),
  });
  const job = live.data?.job ?? null;
  const logBody = live.data?.logs ?? "";
  const showStale = live.stale && !isSessionExpiredError(live.error);
  const statusLabel = job ? t(presentJobStatus(job.status).labelKey) : "";

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logBody]);

  const canCancel = job && (job.status === "queued" || job.status === "running");
  const errorLine = job?.error_code
    ? formatJobError(t, job.error_code, job.error_message)
    : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("jobs.detail.title")}
      size="xl"
    >
      <LiveStatusAnnouncer text={statusLabel} />
      {showStale ? (
        <StaleNotice hasData={job != null} onRetry={() => void live.refresh()} />
      ) : null}
      {!job && live.loading ? (
        <Text size="sm" c="dimmed">
          {t("jobs.detail.loading")}
        </Text>
      ) : job ? (
        <Stack gap="md">
          <Group gap="sm" wrap="wrap">
            <JobStatusBadge status={job.status} />
            <Text size="sm" ff="monospace">
              {job.id}
            </Text>
            <Text size="sm">{job.summary || "—"}</Text>
          </Group>
          <Group gap="xl" wrap="wrap">
            <Text size="sm">
              <Text span c="dimmed">
                {t("jobs.fields.kind")}:{" "}
              </Text>
              {t(jobKindLabelKey(job.kind))}
            </Text>
            <Text size="sm">
              <Text span c="dimmed">
                {t("jobs.fields.trigger")}:{" "}
              </Text>
              {formatJobTrigger(job, t)}
            </Text>
            <Text size="sm">
              <Text span c="dimmed">
                {t("jobs.fields.created")}:{" "}
              </Text>
              {formatInstant(job.created_at)}
            </Text>
            {job.started_at ? (
              <Text size="sm">
                <Text span c="dimmed">
                  {t("jobs.fields.started")}:{" "}
                </Text>
                {formatInstant(job.started_at)}
              </Text>
            ) : null}
            {job.finished_at ? (
              <Text size="sm">
                <Text span c="dimmed">
                  {t("jobs.fields.finished")}:{" "}
                </Text>
                {formatInstant(job.finished_at)}
              </Text>
            ) : null}
            <Text size="sm">
              <Text span c="dimmed">
                {t("jobs.fields.duration")}:{" "}
              </Text>
              {formatJobDuration(job)}
            </Text>
            {job.running_timeout_sec != null ? (
              <Text size="sm">
                <Text span c="dimmed">
                  {t("jobs.fields.runningTimeout")}:{" "}
                </Text>
                {job.running_timeout_sec}s
              </Text>
            ) : null}
          </Group>
          {errorLine ? (
            <Stack gap={4}>
              <Text size="sm" c="red">
                {errorLine.text}
              </Text>
              {errorLine.catalogued && errorLine.occurrence ? (
                <ProblemDetails
                  detail={errorLine.occurrence}
                  requestId={null}
                  labels={{
                    summary: t("form.error.details"),
                    requestId: t("common.requestId"),
                    copy: t("form.error.copy"),
                    copied: t("common.copy.success"),
                    copyFailed: t("common.copy.failed"),
                  }}
                />
              ) : null}
            </Stack>
          ) : null}

          <Stack gap="xs">
            <Text fw={600} size="sm">
              {t("jobs.fields.result")}
            </Text>
            <Code block style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(job.result, null, 2)}
            </Code>
          </Stack>

          <Group justify="space-between" align="center">
            <Text fw={600} size="sm">
              {t("jobs.logs")}
            </Text>
            <Group gap="xs">
              <Button
                size="xs"
                variant="default"
                loading={live.refreshing}
                onClick={() => void live.refresh()}
              >
                {t("jobs.pollRefresh")}
              </Button>
              {canCancel ? (
                <JobCancelButton
                  jobId={job.id}
                  recordName={job.summary || job.id}
                  onCancelled={async () => {
                    await live.refresh();
                    onChanged?.();
                  }}
                />
              ) : null}
            </Group>
          </Group>

          <ScrollArea h={280} type="auto" offsetScrollbars>
            <Code block style={{ whiteSpace: "pre-wrap", minHeight: 260 }}>
              {logBody || t("jobs.logs.empty")}
              <div ref={logEndRef} />
            </Code>
          </ScrollArea>
        </Stack>
      ) : null}
    </Modal>
  );
}
