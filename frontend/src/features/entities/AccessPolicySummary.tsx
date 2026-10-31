"use client";

import { Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { StatusBadge } from "@/components/display/StatusBadge";
import {
  combinationBudgetVisible,
  formatGrantLine,
  viewsNeedAttention,
  viewsStatusKey,
} from "@/features/entities/accessLogic";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { SectionHeader } from "@/components/layout/SectionHeader";

type Props = {
  summary: AccessSummary;
};

export function AccessPolicySummary({ summary }: Props) {
  const t = useTranslate();
  const attributeIds = summary.ladders.map((ladder) => ladder.attribute_id);
  const nameOf = (id: string) =>
    summary.ladders.find((ladder) => ladder.attribute_id === id)?.attribute_name ?? id;
  const typeOf = (id: string) =>
    summary.ladders.find((ladder) => ladder.attribute_id === id)?.type ?? null;
  const attention = viewsNeedAttention(summary);
  const viewKey = viewsStatusKey(summary);
  const budget = combinationBudgetVisible(summary.views);
  const over =
    summary.views.subjects_over_limit > 0 ||
    summary.views.combinations > summary.views.combination_limit;

  return (
    <Stack gap="sm">
      <SectionHeader order={4} title={t("entities.access.summary.title")} />
      {summary.grants.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("entities.access.summary.nobody")}
        </Text>
      ) : (
        <Stack gap={4}>
          {summary.grants.map((grant) => {
            const profile = summary.profiles.find((item) => item.id === grant.profile_id);
            return (
              <Text key={grant.id} size="sm">
                {formatGrantLine(t, {
                  subject: grant.subject.display_name || grant.subject.id,
                  profileName: profile?.name ?? grant.profile_id,
                  actions: grant.actions,
                  broken: grant.broken || Boolean(grant.subject.missing),
                  rowRule: grant.row_rule,
                  columns: profile?.columns ?? [],
                  attributeIds,
                  attributeName: nameOf,
                  attributeType: typeOf,
                })}
              </Text>
            );
          })}
        </Stack>
      )}
      {attention || budget ? (
        <Group gap="xs">
          {attention ? (
            <StatusBadge
              tone={summary.views.state === "failed" ? "danger" : "warning"}
              labelKey={viewKey}
              explanation={t(viewKey)}
            />
          ) : null}
          {budget ? (
            <StatusBadge
              tone={over ? "danger" : "warning"}
              labelKey={t("entities.access.combinations", {
                count: summary.views.combinations,
                limit: summary.views.combination_limit,
              })}
              explanation={over ? t("entities.access.overLimit") : null}
            />
          ) : null}
        </Group>
      ) : null}
    </Stack>
  );
}
