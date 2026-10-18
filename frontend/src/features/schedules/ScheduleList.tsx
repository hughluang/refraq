"use client";

import { Button, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { listSchedules } from "@/features/schedules/api";
import { ScheduleEnabledControl } from "@/features/schedules/ScheduleEnabledControl";
import { ScheduleCadence } from "@/features/schedules/ScheduleCadence";
import { ScheduleFormModal } from "@/features/schedules/ScheduleFormModal";
import { ScheduleIdentityCell } from "@/features/schedules/ScheduleIdentityCell";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRunStrip } from "@/features/schedules/ScheduleRunStrip";
import { ScheduleTableHead } from "@/features/schedules/ScheduleTableHead";
import { ScheduleRowActions } from "@/features/schedules/ScheduleRowActions";
import { formatScheduleNextRun } from "@/features/schedules/nextRunPreview";
import {
  isChannelRunSchedule,
  scheduleIdentityLabel,
} from "@/features/schedules/scheduleIdentity";
import type { ScheduledTask } from "@/features/schedules/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ScheduleList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);
  const [cronTimezone, setCronTimezone] = useState<string | null>(null);
  const query = useListQuery({ search: false });

  const fetchPage = useCallback(async (page: PageQuery) => {
    const result = await listSchedules(page);
    setCronTimezone(result.cron_timezone);
    return result;
  }, []);
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    page: query.page,
    onPageChange: query.setPage,
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
        head={<ScheduleTableHead />}
      >
        {items.map((task) => (
          <Table.Tr key={task.id}>
            <Table.Td>
              <ScheduleIdentityCell task={task} scope="platform" />
            </Table.Td>
            <Table.Td>
              <ScheduleCadence task={task} cronTimezone={cronTimezone} />
            </Table.Td>
            <Table.Td>
              <ScheduleEnabledControl
                task={task}
                editable={!isChannelRunSchedule(task)}
                recordName={scheduleIdentityLabel(task, "platform")}
                onChanged={() => reload()}
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
                kind={task.work_kind}
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
