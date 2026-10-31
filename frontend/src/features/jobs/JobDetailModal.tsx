"use client";

import {
  Button,
  Code,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef } from "react";

import { jobKindLabelKey } from "@/components/display/JobReference";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { isSessionExpiredError } from "@/lib/api";

import { getJob, getJobLogs } from "@/features/jobs/api";
import { JobCancelButton } from "@/features/jobs/JobCancelButton";
import { formatJobError } from "@/features/jobs/formatJobError";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useLiveStatus, type LiveRefreshResult } from "@/hooks/useLiveStatus";
import { formatJobDuration } from "@/lib/datetime";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

type Props = {
  jobId: string | null;
  opened: boolean;
  onClose: () => void;
  onChanged?: () => void;
};

export function JobDetailModal({ jobId, opened, onClose, onChanged }: Props) {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const unloadedNotice = useRef(false);
  const tRef = useRef(t);
  tRef.current = t;
  const retryRef = useRef<() => Promise<void>>(async () => {});
  const reportRefreshFailure = (result: LiveRefreshResult) => {
    if (result.ok) return;
    if (isSessionExpiredError(result.error)) return;
    presentProblemNotification(tRef.current, result.error, {
      onRetry: () => {
        void retryRef.current();
      },
    });
  };
  const live = useLiveStatus({
    enabled: opened && Boolean(jobId),
    key: opened ? jobId : null,
    onRefreshResult: reportRefreshFailure,
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
  const sessionExpired = isSessionExpiredError(live.error);
  retryRef.current = () => live.refresh();
  const freshness =
    job && live.stale && !sessionExpired
      ? { updatedAt: live.lastSuccessAt, onRefresh: () => void retryRef.current() }
      : null;
  const unloaded = !job && live.stale && !sessionExpired;
  const statusLabel = job ? t(presentJobStatus(job.status).labelKey) : "";

  useEffect(() => {
    if (!opened || job || !live.stale || sessionExpired) {
      if (job || !live.stale) unloadedNotice.current = false;
      return;
    }
    if (unloadedNotice.current) return;
    unloadedNotice.current = true;
    presentProblemNotification(tRef.current, live.error, {
      onRetry: () => {
        void retryRef.current();
      },
    });
  }, [opened, job, live.error, live.stale, sessionExpired]);

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
      {unloaded ? (
        <UnstyledButton type="button" onClick={() => void retryRef.current()}>
          <StatusBadge tone="danger" labelKey="status.unloaded" />
        </UnstyledButton>
      ) : !job && live.loading ? (
        <Text size="sm" c="dimmed">
          {t("jobs.detail.loading")}
        </Text>
      ) : job ? (
        <Stack gap="md">
          <Group gap="sm" wrap="wrap">
            <JobStatusBadge status={job.status} freshness={freshness} />
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
              {showInstant(job.created_at)}
            </Text>
            {job.started_at ? (
              <Text size="sm">
                <Text span c="dimmed">
                  {t("jobs.fields.started")}:{" "}
                </Text>
                {showInstant(job.started_at)}
              </Text>
            ) : null}
            {job.finished_at ? (
              <Text size="sm">
                <Text span c="dimmed">
                  {t("jobs.fields.finished")}:{" "}
                </Text>
                {showInstant(job.finished_at)}
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
                onClick={() => void retryRef.current()}
              >
                {t("jobs.pollRefresh")}
              </Button>
              {canCancel ? (
                <JobCancelButton
                  jobId={job.id}
                  recordName={job.summary || job.id}
                  onCancelled={async () => {
                    await retryRef.current();
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
