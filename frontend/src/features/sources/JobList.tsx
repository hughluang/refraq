"use client";

import {
  Badge,
  Button,
  Group,
  Select,
  Table,
  Text,
} from "@mantine/core";
import {
  CanAccess,
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  cancelJob,
  enqueueStructureJob,
  listSourceJobs,
  listSources,
} from "@/features/sources/api";
import type { Job, Source } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

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
  const { data: canRun } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });

  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [items, setItems] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadSources = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSources();
      setSources(data.items);
      if (!sourceId && data.items[0]) setSourceId(data.items[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [sourceId]);

  const loadJobs = useCallback(async () => {
    if (!sourceId) {
      setItems([]);
      return;
    }
    try {
      const data = await listSourceJobs(sourceId);
      setItems(data.items);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    }
  }, [sourceId, open]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  if (loading) return <PageLoader />;
  if (error) return <PageError message={error} />;

  return (
    <PageChrome title={t("jobs.title")} description={t("jobs.description")}>
      <Group mb="md" justify="space-between" align="flex-end">
        <Select
          label={t("jobs.fields.source")}
          data={sources.map((s) => ({ value: s.id, label: `${s.key} — ${s.name}` }))}
          value={sourceId}
          onChange={setSourceId}
          searchable
          w={320}
        />
        <Group>
          <Button variant="light" onClick={() => void loadJobs()}>
            {t("jobs.refresh")}
          </Button>
          <CanAccess resource={ModuleId.jobs} action={ModuleAction.list}>
            <Button
              loading={busy}
              disabled={!sourceId || !canRun?.can}
              onClick={async () => {
                if (!sourceId) return;
                setBusy(true);
                try {
                  await enqueueStructureJob(sourceId);
                  open?.({
                    type: "success",
                    message: t("jobs.enqueue.success"),
                  });
                  await loadJobs();
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
              {t("jobs.enqueue")}
            </Button>
          </CanAccess>
        </Group>
      </Group>

      {!sourceId || items.length === 0 ? (
        <EmptyState message={t("jobs.empty")} />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>id</Table.Th>
              <Table.Th>{t("jobs.fields.kind")}</Table.Th>
              <Table.Th>{t("jobs.fields.status")}</Table.Th>
              <Table.Th>{t("jobs.fields.error")}</Table.Th>
              <Table.Th>{t("jobs.fields.created")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((job) => (
              <Table.Tr key={job.id}>
                <Table.Td>
                  <Text size="sm" ff="monospace">
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
                  <Text size="sm" c="dimmed" lineClamp={2}>
                    {job.error_code
                      ? `${job.error_code}: ${job.error_message ?? ""}`
                      : "—"}
                  </Text>
                </Table.Td>
                <Table.Td>{job.created_at}</Table.Td>
                <Table.Td>
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
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </PageChrome>
  );
}
