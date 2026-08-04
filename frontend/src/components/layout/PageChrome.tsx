"use client";

import { Group, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

import { PageBreadcrumb } from "@/components/layout/PageBreadcrumb";

type PageChromeProps = {
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
};

export function PageChrome({
  title,
  description,
  actions,
  children,
}: PageChromeProps) {
  return (
    <Stack gap="md">
      <PageBreadcrumb />
      <Group justify="space-between" align="flex-start" gap="md" wrap="wrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Title order={2}>{title}</Title>
          {description ? (
            <Text size="sm" c="dimmed">
              {description}
            </Text>
          ) : null}
        </Stack>
        {actions ? <Group gap="sm">{actions}</Group> : null}
      </Group>
      {children}
    </Stack>
  );
}
