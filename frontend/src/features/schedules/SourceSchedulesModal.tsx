"use client";

import { Button, Group, Modal, Switch, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import {
  listSourceSchedules,
  patchSchedule,
} from "@/features/schedules/api";
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

type Props = {
  sourceId: string | null;
  sourceLabel?: string;
  opened: boolean;
  onClose: () => void;
};

export function SourceSchedulesModal({
  sourceId,
  sourceLabel,
  opened,
  onClose,
}: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const [items, setItems] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [jobsTask, setJobsTask] = useState<ScheduledTask | null>(null);

  const load = useCallback(async () => {
    if (!sourceId) {
      setItems([]);
      setError(null);
      return;
    }
    setLoading(true);
    try {
      const data = await listSourceSchedules(sourceId);
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
    setCreating(false);
    setEditing(null);
    setJobsTask(null);
  }, [opened, load]);

  return (
    <Modal.Stack>
      <Modal
        opened={opened}
        onClose={onClose}
        title={
          sourceLabel
            ? `${t("schedules.related.title")} · ${sourceLabel}`
            : t("schedules.related.title")
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
            {t("schedules.refresh")}
          </Button>
          <Button size="xs" onClick={() => setCreating(true)}>
            {t("schedules.create")}
          </Button>
        </Group>
        {error && items.length === 0 ? (
          <PageError message={error} />
        ) : items.length === 0 ? (
          <EmptyState message={t("schedules.related.empty")} />
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("schedules.fields.name")}</Table.Th>
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
      </Modal>
      <ScheduleFormModal
        opened={creating}
        sourceId={sourceId ?? undefined}
        sourceLabel={sourceLabel}
        onClose={() => setCreating(false)}
        onSaved={() => void load()}
      />
      <ScheduleFormModal
        opened={editing !== null}
        schedule={editing}
        sourceLabel={sourceLabel}
        onClose={() => setEditing(null)}
        onSaved={() => void load()}
      />
      <ScheduleJobsModal
        scheduleId={jobsTask?.id ?? null}
        scheduleLabel={jobsTask?.name}
        opened={jobsTask !== null}
        onClose={() => setJobsTask(null)}
      />
    </Modal.Stack>
  );
}
