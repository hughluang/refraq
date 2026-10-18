"use client";

import { Group } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { DisplayField } from "@/components/display/DisplayField";
import type { BusinessEntity } from "@/features/entities/types";
import { JobReference } from "@/components/display/JobReference";
import type { Instant } from "@/lib/instant";

type Props = {
  entity: BusinessEntity;
  formatInstant: (value: Instant | null | undefined) => string;
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
            <JobReference
              jobId={current.alignment.latest_job_id}
              kind="entity_reconcile"
              status={current.alignment.latest_job_status}
              onOpen={onOpenJob}
            />
          }
        />
      ) : null}
    </Group>
  );
}
