"use client";

import { Button, Group, Modal, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { cancelJob } from "@/features/jobs/api";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { listScheduleJobs } from "@/features/schedules/api";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type Props = {
  scheduleId: string | null;
  scheduleLabel?: string;
  opened: boolean;
  onClose: () => void;
};

export function ScheduleJobsModal({
  scheduleId,
  scheduleLabel,
  opened,
  onClose,
}: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const [detailId, setDetailId] = useState<string | null>(null);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );

  const fetchPage = useCallback(
    (query: PageQuery) => listScheduleJobs(scheduleId as string, query),
    [scheduleId],
  );

  const { items, total, page, setPage, loading, error, reload, pageSize } =
    usePagedList({
      pageSize: PAGE_SIZE,
      fetch: fetchPage,
      resetDeps: [scheduleId],
      enabled: opened && Boolean(scheduleId),
      onError,
    });
  const listPresentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: items.length,
    filtered: false,
  });

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={
          scheduleLabel
            ? `${t("jobs.scheduleJobs.title")} · ${scheduleLabel}`
            : t("jobs.scheduleJobs.title")
        }
        size="xl"
        styles={{
          content: {
            display: "flex",
            flexDirection: "column",
            height: "calc(100dvh - var(--modal-y-offset) * 2)",
          },
          header: { flexShrink: 0 },
          body: {
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          },
        }}
      >
        <Group justify="flex-end" mb="sm" style={{ flexShrink: 0 }}>
            <Button
              size="xs"
              variant="light"
              loading={loading}
              onClick={() => void reload()}
            >
              {t("jobs.refresh")}
            </Button>
          </Group>
          <ListTable
            state={listPresentation.state}
            columnCount={6}
            minWidth={720}
            refreshing={listPresentation.refreshing}
            errorMessage={error}
            onRetry={() => void reload()}
            emptyMessage={t("jobs.scheduleJobs.empty")}
            head={
              <Table.Tr>
                <Table.Th>{t("jobs.fields.summary")}</Table.Th>
                <Table.Th>{t("jobs.fields.status")}</Table.Th>
                <Table.Th>{t("jobs.fields.trigger")}</Table.Th>
                <Table.Th>{t("jobs.fields.created")}</Table.Th>
                <Table.Th>{t("jobs.fields.duration")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            }
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={setPage}
          >
            {items.map((job) => (
              <Table.Tr key={job.id}>
                <Table.Td>
                  <Text size="sm">{job.summary || job.id}</Text>
                  <Text size="xs" c="dimmed" ff="monospace">
                    {job.id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <JobStatusBadge status={job.status} />
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatJobTrigger(job, t)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatInstant(job.created_at)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatJobDuration(job)}</Text>
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => setDetailId(job.id)}
                    >
                      {t("jobs.view")}
                    </Button>
                    {job.status === "queued" || job.status === "running" ? (
                      <Button
                        size="xs"
                        variant="light"
                        color="red"
                        onClick={async () => {
                          try {
                            await cancelJob(job.id);
                            await reload();
                          } catch (err) {
                            open?.({
                              type: "error",
                              message:
                                err instanceof ApiError
                                  ? err.detail
                                  : String(err),
                            });
                          }
                        }}
                      >
                        {t("jobs.cancel")}
                      </Button>
                    ) : null}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </ListTable>
      </Modal>
      <JobDetailModal
        jobId={detailId}
        opened={detailId !== null}
        onClose={() => setDetailId(null)}
        onChanged={() => void reload()}
      />
    </>
  );
}
