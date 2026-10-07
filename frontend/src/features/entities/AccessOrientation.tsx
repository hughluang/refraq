"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import {
  accessChainSteps,
  accessGuide,
  type AccessSectionId,
} from "@/features/entities/accessLogic";
import type { AccessSummary } from "@/features/entities/accessTypes";

type Props = {
  summary: AccessSummary;
  dismissed: boolean;
  onDismiss: () => void;
  onFocus: (id: AccessSectionId) => void;
};

export function AccessOrientation({ summary, dismissed, onDismiss, onFocus }: Props) {
  const t = useTranslate();
  const steps = accessChainSteps({
    ladderCount: summary.ladders.length,
    profileCount: summary.profiles.length,
    grantCount: summary.grants.length,
  });
  const guide = accessGuide({
    ladders: summary.ladders,
    profiles: summary.profiles,
    grants: summary.grants,
    restrictionCount: summary.restrictions.length,
  });
  const guideText =
    guide.kind === "no_attributes"
      ? t("entities.access.ladders.empty")
      : guide.kind === "seed_only"
        ? t("entities.access.guide.seedTitle")
        : guide.kind === "unused_profiles"
          ? t("entities.access.guide.unused", {
              names: guide.names.join(t("entities.access.summary.actionJoin")),
            })
          : "";

  return (
    <Stack gap="sm">
      <Group gap="xs" wrap="wrap">
        {steps.map((step, index) => (
          <Group key={step.id} gap="xs">
            {index > 0 ? (
              <Text size="sm" c="dimmed">
                →
              </Text>
            ) : null}
            <Button
              variant="subtle"
              size="compact-sm"
              fw={step.emphasis ? 700 : 500}
              onClick={() => onFocus(step.id)}
            >
              {t(`entities.access.chain.${step.id}`)}
            </Button>
          </Group>
        ))}
      </Group>
      {!dismissed && guide.kind !== "none" ? (
        <Stack gap="xs">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Text size="sm" fw={guide.kind === "seed_only" ? 600 : undefined}>
              {guideText}
            </Text>
            <Button size="compact-xs" variant="subtle" onClick={onDismiss}>
              {t("entities.access.guide.dismiss")}
            </Button>
          </Group>
          {guide.kind === "seed_only" ? (
            <Group gap="xs">
              <Button size="sm" variant="light" onClick={() => onFocus("grants")}>
                {t("entities.access.guide.seedSame")}
              </Button>
              <Button size="sm" variant="default" onClick={() => onFocus("ladders")}>
                {t("entities.access.guide.seedVague")}
              </Button>
              <Button size="sm" variant="default" onClick={() => onFocus("restrictions")}>
                {t("entities.access.guide.seedHide")}
              </Button>
            </Group>
          ) : null}
        </Stack>
      ) : null}
    </Stack>
  );
}
