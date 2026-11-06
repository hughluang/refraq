"use client";

import { Box, Button, Code, Stack, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { SectionHeader } from "@/components/layout/SectionHeader";
import {
  mcpClientConfig,
  type McpCatalog,
} from "@/features/account/mcp-api";
import { apiClient } from "@/lib/api";
import { copyText } from "@/lib/copy-text";
import { problemMessage } from "@/lib/problem";

type McpEndpointCardProps = {
  catalogPath: string;
  fallbackPath: string;
  titleKey: string;
  descriptionKey: string;
};

function McpEndpointCard({
  catalogPath,
  fallbackPath,
  titleKey,
  descriptionKey,
}: McpEndpointCardProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [catalog, setCatalog] = useState<McpCatalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient<McpCatalog>(catalogPath)
      .then((data) => {
        if (!cancelled) {
          setCatalog(data);
          setLoadError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(problemMessage(t, err, t("account.mcp.error")));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [catalogPath, t]);

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const publicPath = catalog?.public_path ?? fallbackPath;
  const configText = useMemo(
    () => (origin ? mcpClientConfig(origin, publicPath) : ""),
    [origin, publicPath],
  );

  async function copyConfig() {
    try {
      await copyText(configText);
      open?.({
        type: "success",
        message: t("common.copy.success"),
      });
    } catch {
      open?.({
        type: "error",
        message: t("common.copy.failed"),
      });
    }
  }

  return (
    <Stack gap="sm">
      <SectionHeader
        title={t(titleKey)}
        description={t(descriptionKey)}
        order={4}
      />
      <Box pos="relative">
        <Code block style={{ paddingRight: 200 }}>
          {configText}
        </Code>
        <Button
          size="compact-sm"
          pos="absolute"
          top={8}
          right={8}
          onClick={() => void copyConfig()}
          disabled={!configText}
        >
          {t("account.mcp.copy")}
        </Button>
      </Box>
      {loadError ? (
        <Text size="sm" c="red">
          {loadError}
        </Text>
      ) : null}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t("account.mcp.tools.name")}</Table.Th>
            <Table.Th>{t("account.mcp.tools.permission")}</Table.Th>
            <Table.Th>{t("account.mcp.tools.description")}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(catalog?.tools ?? []).map((tool) => (
            <Table.Tr key={tool.name}>
              <Table.Td>
                <Code>{tool.name}</Code>
              </Table.Td>
              <Table.Td>{tool.permission}</Table.Td>
              <Table.Td>{tool.description}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {catalog && catalog.tools.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("account.mcp.tools.empty")}
        </Text>
      ) : null}
    </Stack>
  );
}

export function McpSection() {
  const t = useTranslate();

  return (
    <Stack gap="lg">
      <SectionHeader
        title={t("account.mcp.title")}
        description={t("account.mcp.description")}
        order={4}
      />
      <Text size="sm">{t("account.mcp.authHint")}</Text>
      <McpEndpointCard
        catalogPath="/mcp/catalog"
        fallbackPath="/mcp"
        titleKey="account.mcp.metadata.title"
        descriptionKey="account.mcp.metadata.description"
      />
      <McpEndpointCard
        catalogPath="/mcp/entity/catalog"
        fallbackPath="/mcp/entity"
        titleKey="account.mcp.entity.title"
        descriptionKey="account.mcp.entity.description"
      />
    </Stack>
  );
}
