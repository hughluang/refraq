"use client";

import { Skeleton, Stack } from "@mantine/core";

type PageBodySkeletonProps = {
  /** Number of skeleton rows (default 6). */
  rows?: number;
};

/** Content-area placeholder that keeps PageChrome visible while data loads. */
export function PageBodySkeleton({ rows = 6 }: PageBodySkeletonProps) {
  return (
    <Stack gap="sm" py="xs">
      <Skeleton height={14} width="30%" radius="sm" />
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton
          key={index}
          height={36}
          radius="sm"
          width={index === rows - 1 ? "70%" : "100%"}
        />
      ))}
    </Stack>
  );
}
