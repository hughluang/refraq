"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";

export function McpEntityDetail() {
  const t = useTranslate();
  return (
    <PageChrome title={t("mcp.entity.title")}>
      <Stack gap="sm">
        <Text>{t("mcp.entity.identity")}</Text>
        <ConsoleLink href="/console/mcp">{t("mcp.back")}</ConsoleLink>
      </Stack>
    </PageChrome>
  );
}
