"use client";

import { Group, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

type SectionHeaderProps = {
  title: string;
  description?: string;
  actions?: ReactNode;
  order: 2 | 4;
};

export function SectionHeader({
  title,
  description,
  actions,
  order,
}: SectionHeaderProps) {
  return (
    <Group justify="space-between" align="flex-start" gap="md" wrap="wrap">
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <Title order={order}>{title}</Title>
        {description ? (
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        ) : null}
      </Stack>
      {actions ? <Group gap="sm">{actions}</Group> : null}
    </Group>
  );
}
