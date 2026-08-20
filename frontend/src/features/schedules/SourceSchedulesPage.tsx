"use client";

import { Button, Group, Modal, Switch, Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  listSourceSchedules,
  patchSchedule,
} from "@/features/schedules/api";
import { ScheduleFormModal } from "@/features/schedules/ScheduleFormModal";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRowActions } from "@/features/schedules/ScheduleRowActions";
import type { ScheduledTask } from "@/features/schedules/types";
import { getSource } from "@/features/sources/api/sources";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

function cadenceLabel(task: ScheduledTask): string {
  if (task.interval_seconds) return `${task.interval_seconds}s`;
  return task.cron ?? "—";
}

function timezoneLabel(task: ScheduledTask): string {
  if (task.interval_seconds) return "—";
  return task.schedule_timezone;
}

type Props = {
  sourceId: string;
};

export function SourceSchedulesPage({ sourceId }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const { data: canRun, isLoading: canLoading } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });

  const [sourceLabel, setSourceLabel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback(
    (query: PageQuery) => listSourceSchedules(sourceId, query),
    [sourceId],
  );
  const { items, total, page, setPage, loading, error, reload, pageSize } =
    usePagedList({
      pageSize: PAGE_SIZE,
      fetch: fetchPage,
      resetDeps: [sourceId],
      enabled: Boolean(canRun?.can),
      onError,
    });
  const listPresentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: items.length,
    filtered: false,
  });

  useEffect(() => {
    if (!canRun?.can) return;
    void getSource(sourceId)
      .then((res) => {
        setSourceLabel(`${res.source.key} — ${res.source.name}`);
      })
      .catch(() => setSourceLabel(null));
  }, [sourceId, canRun?.can]);

  const aclPending = canLoading || canRun === undefined;

  if (!aclPending && canRun && !canRun.can) {
    return <ForbiddenState reason={canRun.reason} />;
  }

  const title = sourceLabel
    ? `${t("schedules.related.title")} · ${sourceLabel}`
    : `${t("schedules.related.title")} · ${sourceId}`;

  return (
    <>
      <PageChrome
        title={title}
        description={t("schedules.related.description")}
        actions={
          <Group gap="xs">
            <Button
              component={Link}
              href="/console/sources"
              variant="default"
              size="sm"
            >
              {t("schedules.related.backToSources")}
            </Button>
            <Button
              size="sm"
              variant="light"
              loading={loading}
              disabled={aclPending || !canRun?.can}
              onClick={() => void reload()}
            >
              {t("schedules.refresh")}
            </Button>
            <Button
              size="sm"
              disabled={aclPending || !canRun?.can}
              onClick={() => setCreating(true)}
            >
              {t("schedules.create")}
            </Button>
          </Group>
        }
      >
        {aclPending ? (
          <PageBodySkeleton />
        ) : (
          <ListTable
            state={listPresentation.state}
            columnCount={8}
            refreshing={listPresentation.refreshing}
            errorMessage={error}
            onRetry={() => void reload()}
            emptyMessage={t("schedules.related.empty")}
            head={
              <Table.Tr>
                <Table.Th>{t("schedules.fields.name")}</Table.Th>
                <Table.Th>{t("schedules.fields.kind")}</Table.Th>
                <Table.Th>{t("schedules.fields.cadence")}</Table.Th>
                <Table.Th>{t("schedules.fields.timezone")}</Table.Th>
                <Table.Th>{t("schedules.fields.enabled")}</Table.Th>
                <Table.Th>{t("schedules.fields.nextRun")}</Table.Th>
                <Table.Th>{t("schedules.fields.lastJob")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            }
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={setPage}
          >
            {items.map((task) => (
              <Table.Tr key={task.id}>
                <Table.Td>
                  <Text size="sm">{task.name}</Text>
                  <Text size="xs" c="dimmed" ff="monospace">
                    {task.id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {task.work_kind
                      ? t(`schedules.workKind.${task.work_kind}`)
                      : "—"}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {cadenceLabel(task)}
                  </Text>
                </Table.Td>
                <Table.Td>{timezoneLabel(task)}</Table.Td>
                <Table.Td>
                  <Switch
                    checked={task.enabled}
                    onChange={async (event) => {
                      try {
                        await patchSchedule(task.id, {
                          enabled: event.currentTarget.checked,
                        });
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
                  />
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {!task.enabled
                      ? t("schedules.fields.nextRunPaused")
                      : task.next_run_at
                        ? formatInstant(task.next_run_at)
                        : "—"}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {task.last_job ? (
                    <>
                      <Text size="sm">
                        {task.last_job.finished_at
                          ? formatInstant(task.last_job.finished_at)
                          : task.last_job.created_at
                            ? formatInstant(task.last_job.created_at)
                            : "—"}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {task.last_job.status}
                        {task.last_job.error_code
                          ? ` · ${task.last_job.error_code}`
                          : ""}
                      </Text>
                    </>
                  ) : (
                    <Text size="sm">—</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <ScheduleRowActions
                    task={task}
                    onEdit={() => setEditing(task)}
                    onJobs={() => setJobsTask(task)}
                    onChanged={() => void reload()}
                  />
                </Table.Td>
              </Table.Tr>
            ))}
          </ListTable>
        )}
      </PageChrome>
      <Modal.Stack>
        <ScheduleFormModal
          opened={creating}
          sourceId={sourceId}
          sourceLabel={sourceLabel ?? undefined}
          onClose={() => setCreating(false)}
          onSaved={() => void reload()}
        />
        <ScheduleFormModal
          opened={editing !== null}
          schedule={editing}
          sourceLabel={sourceLabel ?? undefined}
          onClose={() => setEditing(null)}
          onSaved={() => void reload()}
        />
        <ScheduleJobsModal
          scheduleId={jobsTask?.id ?? null}
          scheduleLabel={jobsTask?.name}
          opened={jobsTask !== null}
          onClose={() => setJobsTask(null)}
        />
      </Modal.Stack>
    </>
  );
}
