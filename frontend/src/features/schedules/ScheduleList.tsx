"use client";

import { Badge, Button, Switch, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { listSchedules, patchSchedule } from "@/features/schedules/api";
import { ScheduleFormModal } from "@/features/schedules/ScheduleFormModal";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRowActions } from "@/features/schedules/ScheduleRowActions";
import type { ScheduledTask } from "@/features/schedules/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";

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
  const [items, setItems] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listSchedules();
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
    void load();
  }, [load]);

  if (loading) return <PageLoader />;
  if (error && items.length === 0) return <PageError message={error} />;

  return (
    <PageChrome
      title={t("schedules.title")}
      description={t("schedules.description")}
      actions={
        <Button size="sm" variant="light" onClick={() => void load()}>
          {t("schedules.refresh")}
        </Button>
      }
    >
      {items.length === 0 ? (
        <EmptyState message={t("schedules.empty")} />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("schedules.fields.name")}</Table.Th>
              <Table.Th>{t("schedules.fields.kind")}</Table.Th>
              <Table.Th>{t("schedules.fields.target")}</Table.Th>
              <Table.Th>{t("schedules.fields.cadence")}</Table.Th>
              <Table.Th>{t("schedules.fields.timezone")}</Table.Th>
              <Table.Th>{t("schedules.fields.enabled")}</Table.Th>
              <Table.Th>{t("schedules.fields.lastRun")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
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
                        await load();
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
                    {task.last_run_at
                      ? formatInstant(task.last_run_at)
                      : "—"}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <ScheduleRowActions
                    task={task}
                    onEdit={() => setEditing(task)}
                    onJobs={() => setJobsTask(task)}
                    onChanged={() => void load()}
                  />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <ScheduleFormModal
        opened={editing !== null}
        schedule={editing}
        onClose={() => setEditing(null)}
        onSaved={() => void load()}
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
