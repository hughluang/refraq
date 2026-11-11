"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FormSection } from "@/components/form/FormSection";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { McpClientConfiguration } from "@/features/mcp/McpClientConfiguration";
import { McpDiscovery } from "@/features/mcp/McpDiscovery";
import { McpPatGate } from "@/features/mcp/McpPatGate";
import { METADATA_MCP_PUBLIC_PATH } from "@/features/mcp/mcp-api";

export function McpMetadataDetail() {
  const t = useTranslate();
  return (
    <PageChrome title={t("mcp.metadata.title")} breadcrumbLabel={t("mcp.metadata.title")}
      description={t("mcp.metadata.description")}
      actions={<HeaderActions navigation={<Button component={ConsoleLink} href="/console/mcp" size="sm" variant="default">{t("mcp.back")}</Button>} />}>
      <Stack gap="xl" miw={0}>
        <McpClientConfiguration publicPath={METADATA_MCP_PUBLIC_PATH} />
        <FormSection title={t("mcp.pat.title")} columns={1}>
          <McpPatGate endpoint={METADATA_MCP_PUBLIC_PATH} />
        </FormSection>
        <FormSection title={t("mcp.catalog.title")} columns={1}>
          <McpDiscovery endpoint={METADATA_MCP_PUBLIC_PATH} />
        </FormSection>
        <details>
          <summary>{t("mcp.guidance.title")}</summary>
          <Stack gap="sm" mt="sm">
            <Text>{t("mcp.metadata.purpose")}</Text>
            <Text>{t("mcp.metadata.access")}</Text>
            <Text>{t("mcp.troubleshoot.health")}</Text>
            <Text>{t("mcp.troubleshoot.protocol")}</Text>
            <Text>{t("mcp.troubleshoot.compatibility")}</Text>
          </Stack>
        </details>
      </Stack>
    </PageChrome>
  );
}
