"use client";

import { Button, Group, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListPager } from "@/components/display/ListPager";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
import { cancelJob, listJobs } from "@/features/jobs/api";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function JobList() {
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
    (query: PageQuery) => listJobs(query),
    [],
  );

  const {
    items,
    total,
    page,
    setPage,
    loading,
    error,
    reload,
    pageSize,
  } = usePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    onError,
  });

  if (error && items.length === 0 && !loading) {
    return <PageError message={error} />;
  }

  return (
    <PageChrome
      title={t("jobs.title")}
      description={t("jobs.description")}
      actions={
        <Button size="sm" variant="light" onClick={() => void reload()}>
          {t("jobs.refresh")}
        </Button>
      }
    >
      {loading && items.length === 0 ? (
        <PageBodySkeleton />
      ) : items.length === 0 ? (
        <EmptyState message={t("jobs.empty")} />
      ) : (
        <>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("jobs.fields.summary")}</Table.Th>
                <Table.Th>{t("jobs.fields.kind")}</Table.Th>
                <Table.Th>{t("jobs.fields.status")}</Table.Th>
                <Table.Th>{t("jobs.fields.trigger")}</Table.Th>
                <Table.Th>{t("jobs.fields.created")}</Table.Th>
                <Table.Th>{t("jobs.fields.duration")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((job) => (
                <Table.Tr key={job.id}>
                  <Table.Td>
                    <Text size="sm">{job.summary || "—"}</Text>
                    <Text size="xs" c="dimmed" ff="monospace">
                      {job.id}
                    </Text>
                  </Table.Td>
                  <Table.Td>{job.kind}</Table.Td>
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
            </Table.Tbody>
          </Table>
          <ListPager
            page={page}
            pageSize={pageSize}
            total={total}
            onChange={setPage}
          />
        </>
      )}

      <JobDetailModal
        jobId={detailId}
        opened={detailId !== null}
        onClose={() => setDetailId(null)}
        onChanged={() => void reload()}
      />
    </PageChrome>
  );
}
