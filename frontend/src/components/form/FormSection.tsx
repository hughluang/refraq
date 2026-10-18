"use client";

import { Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

import "./form-section.css";

export type FormSectionProps = {
  title: string;
  description?: string;
  /** 2 uses one column until the section is at least 36rem wide. */
  columns?: 1 | 2;
  /** Section title. Never a page-level heading. */
  order?: 2 | 3;
  children: ReactNode;
};

export function FormSection({
  title,
  description,
  columns = 2,
  order = 2,
  children,
}: FormSectionProps) {
  return (
    <Stack className="form-section" gap="sm" component="section">
      <Stack gap={4}>
        <Title order={order}>{title}</Title>
        {description ? (
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        ) : null}
      </Stack>
      <div className="form-section__grid" data-columns={columns}>
        {children}
      </div>
    </Stack>
  );
}
