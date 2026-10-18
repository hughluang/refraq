"use client";

import { Button, Group, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { toneMantineColor } from "@/components/display/statusTone";

type Props = {
  onRetry: () => void;
  /** When false, the notice says the status could not be loaded. */
  hasData?: boolean;
};

export function StaleNotice({ onRetry, hasData = true }: Props) {
  const t = useTranslate();
  const color = toneMantineColor("warning");
  return (
    <Group gap="xs" wrap="nowrap">
      <Text size="sm" c={color}>
        {hasData ? t("liveStatus.stale") : t("liveStatus.unavailable")}
      </Text>
      <Button type="button" size="compact-xs" variant="light" color={color} onClick={onRetry}>
        {t("common.retry")}
      </Button>
    </Group>
  );
}
