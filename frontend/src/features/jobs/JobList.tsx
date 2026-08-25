"use client";

import { Button, Group, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { cancelJob, listJobs } from "@/features/jobs/api";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function JobList() {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const [detailId, setDetailId] = useState<string | null>(null);

  const fetchPage = useCallback(
    (query: PageQuery) => listJobs(query),
    [],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
  });
  const { items, reload } = list;

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
      <ListTable
        list={list}
        columnCount={7}
        emptyMessage={t("jobs.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("jobs.fields.summary")}</Table.Th>
            <Table.Th>{t("jobs.fields.kind")}</Table.Th>
            <Table.Th>{t("jobs.fields.status")}</Table.Th>
            <Table.Th>{t("jobs.fields.trigger")}</Table.Th>
            <Table.Th>{t("jobs.fields.created")}</Table.Th>
            <Table.Th>{t("jobs.fields.duration")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
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
      </ListTable>

      <JobDetailModal
        jobId={detailId}
        opened={detailId !== null}
        onClose={() => setDetailId(null)}
        onChanged={() => void reload()}
      />
    </PageChrome>
  );
}
