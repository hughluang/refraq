"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { McpClientConfiguration } from "@/features/mcp/McpClientConfiguration";
import { METADATA_MCP_PUBLIC_PATH } from "@/features/mcp/mcp-api";

export function McpMetadataDetail() {
  const t = useTranslate();
  return (
    <PageChrome title={t("mcp.metadata.title")}>
      <Stack gap="sm">
        <Text>{t("mcp.metadata.identity")}</Text>
        <Text>{t("mcp.metadata.purpose")}</Text>
        <Text>{t("mcp.metadata.character")}</Text>
        <Text>{t("mcp.metadata.access")}</Text>
        <McpClientConfiguration publicPath={METADATA_MCP_PUBLIC_PATH} />
        <ConsoleLink href="/console/mcp">{t("mcp.back")}</ConsoleLink>
      </Stack>
    </PageChrome>
  );
}
