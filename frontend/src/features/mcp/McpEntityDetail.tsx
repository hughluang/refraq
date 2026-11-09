"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { McpClientConfiguration } from "@/features/mcp/McpClientConfiguration";
import { ENTITY_MCP_PUBLIC_PATH } from "@/features/mcp/mcp-api";

export function McpEntityDetail() {
  const t = useTranslate();
  return (
    <PageChrome title={t("mcp.entity.title")}>
      <Stack gap="sm">
        <Text>{t("mcp.entity.identity")}</Text>
        <Text>{t("mcp.entity.purpose")}</Text>
        <Text>{t("mcp.entity.access")}</Text>
        <Text>{t("mcp.entity.profile")}</Text>
        <Text>{t("mcp.entity.visibility")}</Text>
        <Text>{t("mcp.entity.journey")}</Text>
        <Text>{t("mcp.entity.validate")}</Text>
        <Text>{t("mcp.entity.masks")}</Text>
        <McpClientConfiguration publicPath={ENTITY_MCP_PUBLIC_PATH} />
        <ConsoleLink href="/console/mcp">{t("mcp.back")}</ConsoleLink>
      </Stack>
    </PageChrome>
  );
}
