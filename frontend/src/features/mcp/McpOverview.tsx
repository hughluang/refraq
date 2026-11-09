"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";

export function McpOverview() {
  const t = useTranslate();
  return (
    <PageChrome title={t("mcp.title")} description={t("mcp.description")}>
      <Stack gap="lg">
        <Stack gap="xs">
          <Text fw={600}>{t("mcp.metadata.title")}</Text>
          <Text>{t("mcp.metadata.summary")}</Text>
          <ConsoleLink href="/console/mcp/metadata">{t("mcp.metadata.open")}</ConsoleLink>
        </Stack>
        <Stack gap="xs">
          <Text fw={600}>{t("mcp.entity.title")}</Text>
          <Text>{t("mcp.entity.summary")}</Text>
          <ConsoleLink href="/console/mcp/entity">{t("mcp.entity.open")}</ConsoleLink>
        </Stack>
      </Stack>
    </PageChrome>
  );
}
