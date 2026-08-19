"use client";

import { Badge, Button, Switch, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { listSchedules, patchSchedule } from "@/features/schedules/api";
import { ScheduleFormModal } from "@/features/schedules/ScheduleFormModal";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRowActions } from "@/features/schedules/ScheduleRowActions";
import type { ScheduledTask } from "@/features/schedules/types";
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

function targetLabel(task: ScheduledTask): string {
  return task.target?.source_key || task.target?.source_id || "—";
}

export function ScheduleList() {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback(
    (query: PageQuery) => listSchedules(query),
    [],
  );
  const { items, total, page, setPage, loading, error, reload, pageSize } =
    usePagedList({
      pageSize: PAGE_SIZE,
      fetch: fetchPage,
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
    <PageChrome
      title={t("schedules.title")}
      description={t("schedules.description")}
      actions={
        <Button size="sm" variant="light" onClick={() => void reload()}>
          {t("schedules.refresh")}
        </Button>
      }
    >
      <ListTable
        state={listPresentation.state}
        columnCount={9}
        refreshing={listPresentation.refreshing}
        errorMessage={error}
        onRetry={() => void reload()}
        emptyMessage={t("schedules.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("schedules.fields.name")}</Table.Th>
            <Table.Th>{t("schedules.fields.kind")}</Table.Th>
            <Table.Th>{t("schedules.fields.target")}</Table.Th>
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
              <Badge variant="light">{task.work_kind ?? "—"}</Badge>
            </Table.Td>
            <Table.Td>
              <Text size="sm">{targetLabel(task)}</Text>
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
                        err instanceof ApiError ? err.detail : String(err),
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
      <ScheduleFormModal
        opened={editing !== null}
        schedule={editing}
        onClose={() => setEditing(null)}
        onSaved={() => void reload()}
      />
      <ScheduleJobsModal
        scheduleId={jobsTask?.id ?? null}
        scheduleLabel={jobsTask?.name}
        opened={jobsTask !== null}
        onClose={() => setJobsTask(null)}
      />
    </PageChrome>
  );
}
