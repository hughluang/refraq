"use client";

import { Button } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { cancelJob } from "@/features/jobs/api";

type Props = {
  jobId: string;
  recordName: string;
  size?: "xs" | "sm";
  onCancelled: () => void | Promise<void>;
};

export function JobCancelButton({
  jobId,
  recordName,
  size = "xs",
  onCancelled,
}: Props) {
  const t = useTranslate();
  const mutation = useConsoleMutation();
  const name = recordName.trim() || jobId;
  return (
    <>
      <Button
        size={size}
        variant="light"
        color="red"
        loading={mutation.submitting}
        onClick={() => {
          mutation.run({
            safety: "confirm",
            recordName: name,
            title: t("jobs.cancel.confirmTitle", { name }),
            consequence: t("jobs.cancel.consequence"),
            confirmLabel: t("jobs.cancel"),
            confirmColor: "red",
            outcome: t("jobs.cancel.outcome"),
            execute: () => cancelJob(jobId),
            onSuccess: () => onCancelled(),
          });
        }}
      >
        {t("jobs.cancel")}
      </Button>
      {mutation.dialog}
    </>
  );
}
