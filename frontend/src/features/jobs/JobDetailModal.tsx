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
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { cancelJob, getJob, getJobLogs } from "@/features/jobs/api";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import type { Job } from "@/features/jobs/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
const POLL_MS = 2000;

type Props = {
  jobId: string | null;
  opened: boolean;
  onClose: () => void;
  onChanged?: () => void;
};

export function JobDetailModal({ jobId, opened, onClose, onChanged }: Props) {
  const formatInstant = useFormatInstant();
  const t = useTranslate();
  const { open } = useNotification();
  const [job, setJob] = useState<Job | null>(null);
  const [logBody, setLogBody] = useState("");
  const [pollingPaused, setPollingPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    if (!jobId) return;
    setLoading(true);
    try {
      const [jobRes, logsRes] = await Promise.all([
        getJob(jobId),
        getJobLogs(jobId),
      ]);
      setJob(jobRes.job);
      setLogBody(logsRes.body);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [jobId, open]);

  useEffect(() => {
    if (!opened || !jobId) {
      setJob(null);
      setLogBody("");
      setPollingPaused(false);
      return;
    }
    void refresh();
  }, [opened, jobId, refresh]);

  useEffect(() => {
    if (!opened || !jobId || pollingPaused) return;
    if (job && TERMINAL.has(job.status)) return;
    const id = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [opened, jobId, pollingPaused, job?.status, refresh]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logBody]);

  const canCancel = job && (job.status === "queued" || job.status === "running");
  const showPollControls = job && !TERMINAL.has(job.status);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("jobs.detail.title")}
      size="xl"
    >
      {!job && loading ? (
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
              {job.kind}
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
          </Group>
          {job.error_code ? (
            <Text size="sm" c="red">
              {job.error_code}: {job.error_message ?? ""}
            </Text>
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
              {showPollControls ? (
                <>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => setPollingPaused((p) => !p)}
                  >
                    {pollingPaused
                      ? t("jobs.pollResume")
                      : t("jobs.pollPause")}
                  </Button>
                  <Button
                    size="xs"
                    variant="default"
                    loading={loading}
                    onClick={() => void refresh()}
                  >
                    {t("jobs.pollRefresh")}
                  </Button>
                </>
              ) : (
                <Button
                  size="xs"
                  variant="default"
                  loading={loading}
                  onClick={() => void refresh()}
                >
                  {t("jobs.pollRefresh")}
                </Button>
              )}
              {canCancel ? (
                <Button
                  size="xs"
                  color="red"
                  variant="light"
                  loading={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await cancelJob(job.id);
                      await refresh();
                      onChanged?.();
                    } catch (err) {
                      open?.({
                        type: "error",
                        message:
                          err instanceof ApiError ? err.detail : String(err),
                      });
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {t("jobs.cancel")}
                </Button>
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
