"use client";

import { Box, Flex, Stack, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useMemo } from "react";

import { JOB_STATUS_COLOR, JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { barHeightRatio, buildRunSlots } from "@/features/schedules/runStrip";
import type { ScheduleRecentJob } from "@/features/schedules/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { formatDurationMs, runDurationMs } from "@/lib/datetime";

const STRIP_HEIGHT = 24;

type Props = {
  jobs: ScheduleRecentJob[];
  onOpenJobs: () => void;
};

export function ScheduleRunStrip({ jobs, onOpenJobs }: Props) {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const { slots, maxMs } = useMemo(() => {
    const at = Date.now();
    const built = buildRunSlots(jobs);
    const durations = built.map((job) => (job ? runDurationMs(job, at) : null));
    return {
      slots: built.map((job, index) => ({ job, ms: durations[index] })),
      maxMs: Math.max(0, ...durations.map((ms) => ms ?? 0)),
    };
  }, [jobs]);

  return (
    <UnstyledButton
      onClick={onOpenJobs}
      aria-label={t("schedules.fields.recentRuns")}
      style={{ display: "block", width: "100%", minWidth: 120 }}
    >
      <Flex gap={2} align="flex-end" h={STRIP_HEIGHT}>
        {slots.map(({ job, ms }, index) => {
          if (!job) {
            return (
              <Box
                key={`empty-${index}`}
                style={{
                  flex: 1,
                  minWidth: 0,
                  height: STRIP_HEIGHT * 0.2,
                  borderRadius: 1,
                  background: "var(--mantine-color-gray-2)",
                }}
              />
            );
          }
          const color = JOB_STATUS_COLOR[job.status];
          return (
            <Tooltip
              key={job.id}
              withArrow
              label={
                <Stack gap={2}>
                  <JobStatusBadge status={job.status} />
                  <Text size="xs">
                    {t("jobs.fields.started")}: {formatInstant(job.started_at)}
                  </Text>
                  <Text size="xs">
                    {t("jobs.fields.duration")}: {ms === null ? "—" : formatDurationMs(ms)}
                  </Text>
                  {job.error_code ? (
                    <Text size="xs">
                      {t("jobs.fields.error")}: {job.error_code}
                    </Text>
                  ) : null}
                </Stack>
              }
            >
              <Box
                style={{
                  flex: 1,
                  minWidth: 0,
                  height: STRIP_HEIGHT * barHeightRatio(ms, maxMs),
                  borderRadius: 1,
                  background: `var(--mantine-color-${color}-6)`,
                }}
              />
            </Tooltip>
          );
        })}
      </Flex>
    </UnstyledButton>
  );
}
