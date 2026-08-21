"use client";

import { Button, Group } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import {
  deleteSchedule,
  runSchedule,
} from "@/features/schedules/api";
import type { ScheduledTask } from "@/features/schedules/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { ApiError } from "@/lib/api";

type Props = {
  task: ScheduledTask;
  onEdit: () => void;
  onJobs: () => void;
  onChanged: () => void;
};

export function ScheduleRowActions({
  task,
  onEdit,
  onJobs,
  onChanged,
}: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [running, setRunning] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const deleteConfirm = useConfirmAction<ScheduledTask>();

  async function confirmDelete() {
    setDeleting(true);
    try {
      await deleteSchedule(task.id);
      open?.({
        type: "success",
        message: t("schedules.delete.success"),
      });
      deleteConfirm.close();
      onChanged();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <Group gap="xs" wrap="nowrap">
        <Button
          size="xs"
          variant="light"
          loading={running}
          onClick={async () => {
            setRunning(true);
            try {
              await runSchedule(task.id);
              open?.({
                type: "success",
                message: t("schedules.run.success"),
              });
              onChanged();
            } catch (err) {
              open?.({
                type: "error",
                message: err instanceof ApiError ? err.detail : String(err),
              });
            } finally {
              setRunning(false);
            }
          }}
        >
          {t("schedules.run")}
        </Button>
        <Button size="xs" variant="default" onClick={onJobs}>
          {t("jobs.scheduleJobs.open")}
        </Button>
        <Button size="xs" variant="light" onClick={onEdit}>
          {t("schedules.edit")}
        </Button>
        <Button
          size="xs"
          variant="light"
          color="red"
          onClick={() => deleteConfirm.open(task)}
        >
          {t("schedules.delete")}
        </Button>
      </Group>
      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("schedules.delete.confirmTitle")}
        body={t("schedules.delete.confirmBody", { name: task.name })}
        confirmColor="red"
        loading={deleting}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
