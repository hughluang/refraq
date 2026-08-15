"use client";

import { Badge } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

const CLASS_COLOR: Record<string, string> = {
  breaking: "red",
  non_breaking: "blue",
  unchanged: "gray",
};

type Props = {
  value: string | null | undefined;
};

export function StructureDiffClassBadge({ value }: Props) {
  const t = useTranslate();
  if (!value) return null;
  return (
    <Badge color={CLASS_COLOR[value] ?? "gray"} variant="light">
      {t(`structureDiffs.class.${value}`)}
    </Badge>
  );
}
