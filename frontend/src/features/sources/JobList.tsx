"use client";

import { Badge, Button, Group, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { cancelJob, listJobs } from "@/features/sources/api";
import { formatJobTrigger } from "@/features/sources/formatJobTrigger";
import { JobDetailModal } from "@/features/sources/JobDetailModal";
import type { Job } from "@/features/sources/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";

const STATUS_COLOR: Record<string, string> = {
  queued: "blue",
  running: "yellow",
  succeeded: "green",
  failed: "red",
  cancelled: "gray",
};

export function JobList() {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();

  const [items, setItems] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      setItems(data.items);
      setError(null);
    } catch (err) {
      const message = err instanceof ApiError ? err.detail : String(err);
      setError(message);
      open?.({ type: "error", message });
    } finally {
      setLoading(false);
    }
  }, [open]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  if (loading) return <PageLoader />;
  if (error && items.length === 0) return <PageError message={error} />;

  return (
    <PageChrome
      title={t("jobs.title")}
      description={t("jobs.description")}
      actions={
        <Button size="sm" variant="light" onClick={() => void loadJobs()}>
          {t("jobs.refresh")}
        </Button>
      }
    >
      {items.length === 0 ? (
        <EmptyState message={t("jobs.empty")} />
      ) : (
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
                  <Badge color={STATUS_COLOR[job.status] ?? "gray"}>
                    {job.status}
                  </Badge>
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
                            await loadJobs();
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
      )}

      <JobDetailModal
        jobId={detailId}
        opened={detailId !== null}
        onClose={() => setDetailId(null)}
        onChanged={() => void loadJobs()}
      />
    </PageChrome>
  );
}
