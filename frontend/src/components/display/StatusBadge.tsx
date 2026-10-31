"use client";

import { Badge, Group, Tooltip, UnstyledButton, type MantineSize } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ReactElement } from "react";

import { ClockIcon } from "@/components/icons";
import { toneMantineColor, toneVariable, type Tone } from "@/components/display/statusTone";
import { useFormatInstant } from "@/hooks/useFormatInstant";

export type StatusFreshness = {
  /** Last successful update, as platform Instant text. */
  updatedAt: string | null;
  onRefresh: () => void;
};

type Props = {
  tone: Tone;
  labelKey: string;
  size?: MantineSize;
  freshness?: StatusFreshness | null;
  /** Status explanation. Separate from the freshness marker. */
  explanation?: string | null;
};

function explain(node: ReactElement, explanation: string | null | undefined) {
  const text = explanation?.trim() ?? "";
  if (!text) return node;
  return <Tooltip label={text}>{node}</Tooltip>;
}

export function StatusBadge({ tone, labelKey, size, freshness, explanation }: Props) {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const badge = explain(
    <Badge color={toneMantineColor(tone)} variant="light" tt="none" size={size}>
      {t(labelKey)}
    </Badge>,
    explanation,
  );
  if (!freshness) return badge;

  const freshnessLabel = t("status.freshness", {
    time: formatInstant(freshness.updatedAt),
  });
  return (
    <Group gap={4} wrap="nowrap" align="center">
      {badge}
      <Tooltip label={freshnessLabel}>
        <UnstyledButton
          type="button"
          aria-label={freshnessLabel}
          onClick={freshness.onRefresh}
          style={{ color: toneVariable("warning"), display: "inline-flex" }}
        >
          <ClockIcon size={14} />
        </UnstyledButton>
      </Tooltip>
    </Group>
  );
}
