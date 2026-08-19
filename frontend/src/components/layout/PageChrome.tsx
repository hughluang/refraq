"use client";

import { Stack } from "@mantine/core";
import type { ReactNode } from "react";

import { PageBreadcrumb } from "@/components/layout/PageBreadcrumb";
import { SectionHeader } from "@/components/layout/SectionHeader";

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
    <Stack
      gap="md"
      flex={1}
      h="100%"
      mih={0}
      style={{ overflow: "auto" }}
    >
      <PageBreadcrumb />
      <SectionHeader
        title={title}
        description={description}
        actions={actions}
        order={2}
      />
      {children}
    </Stack>
  );
}
