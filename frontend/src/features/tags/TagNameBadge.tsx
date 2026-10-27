"use client";

import { Badge } from "@mantine/core";

type Props = {
  name: string;
};

/** A stored Tag display name. Badge's default uppercase would paint a different word. */
export function TagNameBadge({ name }: Props) {
  return (
    <Badge size="sm" variant="light" color="gray" tt="none">
      {name}
    </Badge>
  );
}
