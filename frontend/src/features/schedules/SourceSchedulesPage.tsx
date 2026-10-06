"use client";

import { Button, Group, Modal, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { SwitchField } from "@/components/form/SwitchField";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  listSourceSchedules,
  patchSchedule,
} from "@/features/schedules/api";
import { ScheduleCadence } from "@/features/schedules/ScheduleCadence";
import { ScheduleFormModal } from "@/features/schedules/ScheduleFormModal";
import { ScheduleIdentityCell } from "@/features/schedules/ScheduleIdentityCell";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRunStrip } from "@/features/schedules/ScheduleRunStrip";
import { ScheduleTableHead } from "@/features/schedules/ScheduleTableHead";
import { ScheduleRowActions } from "@/features/schedules/ScheduleRowActions";
import { formatScheduleNextRun } from "@/features/schedules/nextRunPreview";
import { scheduleIdentityLabel } from "@/features/schedules/scheduleIdentity";
import type { ScheduledTask } from "@/features/schedules/types";
import { getSource } from "@/features/sources/api/sources";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type Props = {
  sourceId: string;
};

export function SourceSchedulesPage({ sourceId }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();

  const [sourceLabel, setSourceLabel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);
  const [cronTimezone, setCronTimezone] = useState<string | null>(null);

  const fetchPage = useCallback(
    async (query: PageQuery) => {
      const page = await listSourceSchedules(sourceId, query);
      setCronTimezone(page.cron_timezone);
      return page;
    },
    [sourceId],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [sourceId],
  });
  const { items, loading, reload } = list;

  useEffect(() => {
    void getSource(sourceId)
      .then((res) => {
        setSourceLabel(`${res.source.key} — ${res.source.name}`);
      })
      .catch(() => setSourceLabel(null));
  }, [sourceId]);

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
              onClick={() => void reload()}
            >
              {t("schedules.refresh")}
            </Button>
            <Button
              size="sm"
              disabled={cronTimezone === null}
              onClick={() => setCreating(true)}
            >
              {t("schedules.create")}
            </Button>
          </Group>
        }
      >
        <ListTable
            list={list}
            columnCount={6}
            emptyMessage={t("schedules.related.empty")}
            head={<ScheduleTableHead />}
          >
            {items.map((task) => (
              <Table.Tr key={task.id}>
                <Table.Td>
                  <ScheduleIdentityCell task={task} scope="source" />
                </Table.Td>
                <Table.Td>
                  <ScheduleCadence task={task} cronTimezone={cronTimezone} />
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
      </PageChrome>
      <Modal.Stack>
        {cronTimezone !== null ? (
          <ScheduleFormModal
            opened={creating}
            sourceId={sourceId}
            sourceLabel={sourceLabel ?? undefined}
            cronTimezone={cronTimezone}
            onClose={() => setCreating(false)}
            onSaved={() => void reload()}
          />
        ) : null}
        {cronTimezone !== null ? (
          <ScheduleFormModal
            opened={editing !== null}
            schedule={editing}
            sourceLabel={sourceLabel ?? undefined}
            cronTimezone={cronTimezone}
            onClose={() => setEditing(null)}
            onSaved={() => void reload()}
          />
        ) : null}
        <ScheduleJobsModal
          scheduleId={jobsTask?.id ?? null}
          scheduleLabel={
            jobsTask ? scheduleIdentityLabel(jobsTask, "source") : undefined
          }
          opened={jobsTask !== null}
          onClose={() => setJobsTask(null)}
        />
      </Modal.Stack>
    </>
  );
}
