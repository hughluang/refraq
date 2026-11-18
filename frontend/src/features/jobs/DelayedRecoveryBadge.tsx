"use client";

import { Badge, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

export function DelayedRecoveryBadge({ recovery }: { recovery: boolean }) {
  const t = useTranslate();
  if (!recovery) return null;
  return (
    <Tooltip label={t("jobs.delayedRecovery.description")} events={{ hover: true, focus: true, touch: false }} multiline w={300}>
      <Badge tabIndex={0} variant="light" tt="none">{t("jobs.delayedRecovery")}</Badge>
    </Tooltip>
  );
}
