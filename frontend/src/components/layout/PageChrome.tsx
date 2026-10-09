"use client";

import { Group, Stack } from "@mantine/core";
import type { ReactNode } from "react";

import { PageBreadcrumb } from "@/components/layout/PageBreadcrumb";
import { SectionHeader } from "@/components/layout/SectionHeader";

type PageChromeProps = {
  title: string;
  titleSlot?: ReactNode;
  titleExtra?: ReactNode;
  description?: string;
  descriptionLineClamp?: number;
  actions?: ReactNode;
  children?: ReactNode;
};

export function PageChrome({
  title,
  titleSlot,
  titleExtra,
  description,
  descriptionLineClamp,
  actions,
  children,
}: PageChromeProps) {
  return (
    <Stack
      gap="md"
      flex={1}
      h="100%"
      mih={0}
      style={{ overflow: "auto" }}
    >
      <PageBreadcrumb />
      {actions ? (
        <Group gap="sm" justify="flex-start" wrap="wrap" align="center">
          {actions}
        </Group>
      ) : null}
      <SectionHeader
        title={title}
        titleSlot={titleSlot}
        titleExtra={titleExtra}
        description={description}
        descriptionLineClamp={descriptionLineClamp}
        order={2}
      />
      {children}
    </Stack>
  );
}
