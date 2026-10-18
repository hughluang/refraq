"use client";

import { Badge, type MantineSize } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { toneMantineColor, type Tone } from "@/components/display/statusTone";

type Props = {
  tone: Tone;
  labelKey: string;
  size?: MantineSize;
};

export function StatusBadge({ tone, labelKey, size }: Props) {
  const t = useTranslate();
  return (
    <Badge color={toneMantineColor(tone)} variant="light" tt="none" size={size}>
      {t(labelKey)}
    </Badge>
  );
}
