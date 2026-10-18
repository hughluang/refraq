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
  order: 1 | 2 | 4;
  pageHeading?: boolean;
};

export function SectionHeader({
  title,
  titleSlot,
  titleExtra,
  description,
  descriptionLineClamp,
  actions,
  order,
  pageHeading = false,
}: SectionHeaderProps) {
  const heading = titleSlot ? (
    <span data-page-heading="" tabIndex={-1} style={{ display: "inline-flex", minWidth: 0 }}>
      {titleSlot}
    </span>
  ) : (
    <Title
      order={pageHeading ? 1 : order}
      size={pageHeading ? "h2" : undefined}
      data-page-heading={pageHeading ? "" : undefined}
      tabIndex={pageHeading ? -1 : undefined}
    >
      {title}
    </Title>
  );
  return (
    <Group justify="space-between" align="flex-start" gap="md" wrap="wrap">
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <Group gap="sm" align="center" wrap="wrap">
          {heading}
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
