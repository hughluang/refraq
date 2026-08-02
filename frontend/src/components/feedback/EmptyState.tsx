"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

type EmptyStateProps = {
  message?: string;
  action?: ReactNode;
};

export function EmptyState({ message, action }: EmptyStateProps) {
  const t = useTranslate();
  return (
    <Stack gap="sm" align="flex-start" py="md">
      <Text c="dimmed">{message ?? t("common.empty")}</Text>
      {action}
    </Stack>
  );
}
