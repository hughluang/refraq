"use client";

import { Skeleton, Stack } from "@mantine/core";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";

export function PageFrameSkeleton() {
  return (
    <Stack gap="md" aria-busy="true">
      <Skeleton height={12} width="18%" radius="sm" />
      <Skeleton height={28} width="36%" radius="sm" />
      <PageBodySkeleton />
    </Stack>
  );
}
