"use client";

import { Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

type EmptyStateProps = {
  message?: string;
};

export function EmptyState({ message }: EmptyStateProps) {
  const t = useTranslate();
  return (
    <Text c="dimmed" py="md">
      {message ?? t("common.empty")}
    </Text>
  );
}
