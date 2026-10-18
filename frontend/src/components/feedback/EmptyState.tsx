"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

import { EmptyIcon } from "@/components/icons";

export type EmptyStateProps = {
  /** One next-step sentence. */
  message?: string;
  icon?: ReactNode;
  /** Primary action, such as the module create control when it is permitted. */
  action?: ReactNode;
};

export function EmptyState({ message, icon, action }: EmptyStateProps) {
  const t = useTranslate();
  return (
    <Stack align="flex-start" gap="xs" py="md">
      {icon ?? <EmptyIcon size={28} aria-hidden />}
      <Text c="dimmed">{message ?? t("common.empty")}</Text>
      {action ?? null}
    </Stack>
  );
}
