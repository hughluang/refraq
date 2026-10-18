"use client";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentEntityStatus } from "@/components/display/statusTone";
import { entityStatus } from "@/features/entities/publishStatus";
import type { BusinessEntity } from "@/features/entities/types";

type Props = {
  entity: BusinessEntity;
};

export function EntityStatusBadge({ entity }: Props) {
  const presentation = presentEntityStatus(entityStatus(entity));
  return <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} />;
}
