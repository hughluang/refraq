"use client";

import { Badge } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import {
  PUBLISH_STATUS_COLOR,
  publishStatusLabelKey,
} from "@/features/entities/publishStatus";
import type { PublishStatus } from "@/features/entities/types";

type Props = {
  publishStatus: PublishStatus;
};

export function PublishStatusBadge({ publishStatus }: Props) {
  const t = useTranslate();
  return (
    <Badge color={PUBLISH_STATUS_COLOR[publishStatus]} variant="light" tt="none">
      {t(publishStatusLabelKey(publishStatus))}
    </Badge>
  );
}
