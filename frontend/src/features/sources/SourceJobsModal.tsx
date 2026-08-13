"use client";

import { Badge, Button, Group, Modal, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { PageError } from "@/components/feedback/PageError";
import { cancelJob, listSourceJobs } from "@/features/sources/api";
import { formatJobTrigger } from "@/features/sources/formatJobTrigger";
import { JobDetailModal } from "@/features/sources/JobDetailModal";
import { JobResultBadge } from "@/features/sources/JobResultBadge";
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

type Props = {
  sourceId: string | null;
  sourceLabel?: string;
  opened: boolean;
  onClose: () => void;
};

export function SourceJobsModal({
  sourceId,
  sourceLabel,
  opened,
  onClose,
}: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const [items, setItems] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sourceId) {
      setItems([]);
      setError(null);
      return;
    }
    setLoading(true);
    try {
      const data = await listSourceJobs(sourceId);
      setItems(data.items);
      setError(null);
    } catch (err) {
      const message = err instanceof ApiError ? err.detail : String(err);
      setError(message);
      open?.({ type: "error", message });
    } finally {
      setLoading(false);
    }
  }, [sourceId, open]);

  useEffect(() => {
    if (opened) {
      void load();
      return;
    }
    setItems([]);
    setError(null);
    setDetailId(null);
  }, [opened, load]);

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={
          sourceLabel
            ? `${t("jobs.sourceJobs.title")} · ${sourceLabel}`
            : t("jobs.sourceJobs.title")
        }
        size="xl"
      >
        <Group justify="flex-end" mb="sm">
          <Button
            size="xs"
            variant="light"
            loading={loading}
            onClick={() => void load()}
          >
            {t("jobs.refresh")}
          </Button>
        </Group>
        {error && items.length === 0 ? (
          <PageError message={error} />
        ) : items.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("jobs.sourceJobs.empty")}
          </Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("jobs.fields.summary")}</Table.Th>
                <Table.Th>{t("jobs.fields.status")}</Table.Th>
                <Table.Th>{t("jobs.fields.result")}</Table.Th>
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
                    <Text size="sm">{job.summary || job.id}</Text>
                    <Text size="xs" c="dimmed" ff="monospace">
                      {job.id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={STATUS_COLOR[job.status] ?? "gray"}>
                      {job.status}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <JobResultBadge value={job.result?.class} />
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
                              await load();
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
      </Modal>
      <JobDetailModal
        jobId={detailId}
        opened={detailId !== null}
        onClose={() => setDetailId(null)}
        onChanged={() => void load()}
      />
    </>
  );
}
