"use client";

import { Group, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

type SectionHeaderProps = {
  title: string;
  titleSlot?: ReactNode;
  titleExtra?: ReactNode;
  description?: string;
  descriptionLineClamp?: number;
  actions?: ReactNode;
  order: 2 | 4;
};

export function SectionHeader({
  title,
  titleSlot,
  titleExtra,
  description,
  descriptionLineClamp,
  actions,
  order,
}: SectionHeaderProps) {
  return (
    <Group justify="space-between" align="flex-start" gap="md" wrap="wrap">
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <Group gap="sm" align="center" wrap="wrap">
          {titleSlot ?? <Title order={order}>{title}</Title>}
          {titleExtra}
        </Group>
        {description ? (
          <Text size="sm" c="dimmed" lineClamp={descriptionLineClamp}>
            {description}
          </Text>
        ) : null}
      </Stack>
      {actions ? <Group gap="sm">{actions}</Group> : null}
    </Group>
  );
}
