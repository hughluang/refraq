"use client";

import { Badge } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

type Props = {
  deprecated: boolean;
};

export function DictionaryStatusBadge({ deprecated }: Props) {
  const t = useTranslate();
  return (
    <Badge color={deprecated ? "red" : "green"} variant="light" tt="none">
      {t(
        deprecated
          ? "dictionaries.status.deprecated"
          : "dictionaries.status.available",
      )}
    </Badge>
  );
}
