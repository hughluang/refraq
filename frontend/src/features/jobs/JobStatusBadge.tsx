"use client";

import { Badge } from "@mantine/core";

const STATUS_COLOR: Record<string, string> = {
  queued: "blue",
  running: "yellow",
  succeeded: "green",
  failed: "red",
  cancelled: "gray",
};

type Props = {
  status: string;
};

export function JobStatusBadge({ status }: Props) {
  return <Badge color={STATUS_COLOR[status] ?? "gray"}>{status}</Badge>;
}
