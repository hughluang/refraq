"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";

export function McpMetadataDetail() {
  const t = useTranslate();
  return (
    <PageChrome title={t("mcp.metadata.title")}>
      <Stack gap="sm">
        <Text>{t("mcp.metadata.identity")}</Text>
        <ConsoleLink href="/console/mcp">{t("mcp.back")}</ConsoleLink>
      </Stack>
    </PageChrome>
  );
}
