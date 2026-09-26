"use client";

import { Button, Group } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { DisplayField } from "@/components/display/DisplayField";
import type { BusinessEntity } from "@/features/entities/types";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";

type Props = {
  entity: BusinessEntity;
  formatInstant: (value: string | null | undefined) => string;
  onOpenJob: (jobId: string | null) => void;
};

export function EntityOverviewTab({
  entity,
  formatInstant,
  onOpenJob,
}: Props) {
  const t = useTranslate();
  const current = entity.current_version;

  return (
    <Group gap="xl" align="flex-start">
      <DisplayField
        label={t("entities.fields.updatedAt")}
        value={formatInstant(entity.updated_at)}
      />
      {current?.alignment.latest_job_id ? (
        <DisplayField
          label={t("entities.fields.publishJob")}
          value={
            <Group gap="xs">
              {current.alignment.latest_job_status &&
              current.publish_status === "publishing" ? (
                <JobStatusBadge status={current.alignment.latest_job_status} />
              ) : null}
              <Button
                size="compact-xs"
                variant="light"
                onClick={() => onOpenJob(current.alignment.latest_job_id)}
              >
                {current.alignment.latest_job_id}
              </Button>
            </Group>
          }
        />
      ) : null}
    </Group>
  );
}
