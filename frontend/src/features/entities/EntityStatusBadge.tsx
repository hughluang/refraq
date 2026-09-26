"use client";

import { Badge } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import {
  ENTITY_STATUS_COLOR,
  entityStatus,
  entityStatusLabelKey,
} from "@/features/entities/publishStatus";
import type { BusinessEntity } from "@/features/entities/types";

type Props = {
  entity: BusinessEntity;
};

export function EntityStatusBadge({ entity }: Props) {
  const t = useTranslate();
  const status = entityStatus(entity);
  return (
    <Badge color={ENTITY_STATUS_COLOR[status]} variant="light" tt="none">
      {t(entityStatusLabelKey(status))}
    </Badge>
  );
}
