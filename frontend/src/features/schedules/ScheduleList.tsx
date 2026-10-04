"use client";

import { Button, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { SwitchField } from "@/components/form/SwitchField";
import { PageChrome } from "@/components/layout/PageChrome";
import { listSchedules, patchSchedule } from "@/features/schedules/api";
import { ScheduleFormModal } from "@/features/schedules/ScheduleFormModal";
import { ScheduleIdentityCell } from "@/features/schedules/ScheduleIdentityCell";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRunStrip } from "@/features/schedules/ScheduleRunStrip";
import { ScheduleRowActions } from "@/features/schedules/ScheduleRowActions";
import { formatScheduleNextRun } from "@/features/schedules/nextRunPreview";
import { scheduleIdentityLabel } from "@/features/schedules/scheduleIdentity";
import type { ScheduledTask } from "@/features/schedules/types";
import { useDisplayZoneId, useFormatInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

function cadenceLabel(task: ScheduledTask): string {
  if (task.interval_seconds) return `${task.interval_seconds}s`;
  return task.cron ?? "—";
}

export function ScheduleList() {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const displayZone = useDisplayZoneId();
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);
  const [cronTimezone, setCronTimezone] = useState<string | null>(null);

  const fetchPage = useCallback(async (query: PageQuery) => {
    const page = await listSchedules(query);
    setCronTimezone(page.cron_timezone);
    return page;
  }, []);
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
  });
  const { items, reload } = list;

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
        list={list}
        columnCount={6}
        emptyMessage={t("schedules.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("schedules.fields.kind")}</Table.Th>
            <Table.Th>{t("schedules.fields.cadence")}</Table.Th>
            <Table.Th>{t("schedules.fields.enabled")}</Table.Th>
            <Table.Th>
              {t("schedules.fields.nextRunInZone", {
                zone:
                  displayZone ?? t("account.fields.displayTimezone.browser"),
              })}
            </Table.Th>
            <Table.Th>{t("schedules.fields.recentRuns")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {items.map((task) => (
          <Table.Tr key={task.id}>
            <Table.Td>
              <ScheduleIdentityCell task={task} scope="platform" />
            </Table.Td>
            <Table.Td>
              <Text size="sm" ff="monospace">
                {cadenceLabel(task)}
              </Text>
            </Table.Td>
            <Table.Td>
              <SwitchField
                editable
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
                {formatScheduleNextRun(
                  task,
                  formatInstant,
                  t("schedules.fields.nextRunPaused"),
                )}
              </Text>
            </Table.Td>
            <Table.Td>
              <ScheduleRunStrip
                jobs={task.recent_jobs}
                onOpenJobs={() => setJobsTask(task)}
              />
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
      {cronTimezone !== null ? (
        <ScheduleFormModal
          opened={editing !== null}
          schedule={editing}
          cronTimezone={cronTimezone}
          onClose={() => setEditing(null)}
          onSaved={() => void reload()}
        />
      ) : null}
      <ScheduleJobsModal
        scheduleId={jobsTask?.id ?? null}
        scheduleLabel={
          jobsTask ? scheduleIdentityLabel(jobsTask, "platform") : undefined
        }
        opened={jobsTask !== null}
        onClose={() => setJobsTask(null)}
      />
    </PageChrome>
  );
}
