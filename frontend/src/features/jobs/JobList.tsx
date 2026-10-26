"use client";

import { Button, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { jobKindLabelKey } from "@/components/display/JobReference";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { cancelJob, listJobs } from "@/features/jobs/api";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { formatJobDuration } from "@/lib/datetime";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function JobList() {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const [detailId, setDetailId] = useState<string | null>(null);

  const query = useListQuery({ search: false });

  const fetchPage = useCallback(
    (pageQuery: PageQuery) => listJobs(pageQuery),
    [],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    page: query.page,
    onPageChange: query.setPage,
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
        {items.map((job) => {
          const recordName = job.summary.trim() || t(jobKindLabelKey(job.kind));
          const cancellable = job.status === "queued" || job.status === "running";
          return (
            <Table.Tr key={job.id}>
              <Table.Td>
                <RecordReference name={recordName} recordKey={job.id} />
              </Table.Td>
              <Table.Td>{t(jobKindLabelKey(job.kind))}</Table.Td>
              <Table.Td>
                <JobStatusBadge status={job.status} />
              </Table.Td>
              <Table.Td>
                <Text size="sm">{formatJobTrigger(job, t)}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm">{showInstant(job.created_at)}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm">{formatJobDuration(job)}</Text>
              </Table.Td>
              <Table.Td>
                <RowActions
                  recordName={recordName}
                  verbs={[
                    {
                      key: "view",
                      label: t("jobs.view"),
                      safety: "immediate",
                      onClick: () => setDetailId(job.id),
                    },
                    {
                      key: "cancel",
                      label: t("jobs.cancel"),
                      color: "red",
                      disabledReason: cancellable
                        ? undefined
                        : t("jobs.cancel.unavailable"),
                      action: {
                        safety: "confirm",
                        recordName,
                        title: t("jobs.cancel.confirmTitle", { name: recordName }),
                        consequence: t("jobs.cancel.consequence"),
                        confirmLabel: t("jobs.cancel"),
                        confirmColor: "red",
                        outcome: t("jobs.cancel.outcome"),
                        execute: () => cancelJob(job.id),
                        onSuccess: () => reload(),
                      },
                    },
                  ]}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
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
