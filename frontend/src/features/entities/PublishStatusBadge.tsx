"use client";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentPublishStatus } from "@/components/display/statusTone";
import type { PublishStatus } from "@/features/entities/types";

type Props = {
  publishStatus: PublishStatus;
};

export function PublishStatusBadge({ publishStatus }: Props) {
  const presentation = presentPublishStatus(publishStatus);
  return <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} />;
}
