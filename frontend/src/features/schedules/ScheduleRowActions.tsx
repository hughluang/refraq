"use client";

import { Button, Group, Modal, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useState } from "react";

import {
  deleteSchedule,
  runSchedule,
} from "@/features/schedules/api";
import type { ScheduledTask } from "@/features/schedules/types";
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
  const [confirmOpen, setConfirmOpen] = useState(false);

  async function confirmDelete() {
    setDeleting(true);
    try {
      await deleteSchedule(task.id);
      open?.({
        type: "success",
        message: t("schedules.delete.success"),
      });
      setConfirmOpen(false);
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
          onClick={() => setConfirmOpen(true)}
        >
          {t("schedules.delete")}
        </Button>
      </Group>
      <Modal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t("schedules.delete.confirmTitle")}
        centered
      >
        <Text size="sm" mb="md">
          {t("schedules.delete.confirmBody", { name: task.name })}
        </Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={() => setConfirmOpen(false)}
            disabled={deleting}
          >
            {t("common.cancel")}
          </Button>
          <Button color="red" loading={deleting} onClick={() => void confirmDelete()}>
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>
    </>
  );
}
