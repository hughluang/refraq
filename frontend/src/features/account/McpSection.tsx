"use client";

import { Box, Button, Code, Stack, Table, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { SectionHeader } from "@/components/layout/SectionHeader";
import {
  mcpClientConfig,
  type McpCatalog,
} from "@/features/account/mcp-api";
import { apiClient, ApiError } from "@/lib/api";

export function McpSection() {
  const t = useTranslate();
  const { open } = useNotification();
  const [catalog, setCatalog] = useState<McpCatalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient<McpCatalog>("/mcp/catalog")
      .then((data) => {
        if (!cancelled) {
          setCatalog(data);
          setLoadError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(
            err instanceof ApiError ? err.detail : t("account.mcp.error"),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const publicPath = catalog?.public_path ?? "/mcp";
  const configText = useMemo(
    () => (origin ? mcpClientConfig(origin, publicPath) : ""),
    [origin, publicPath],
  );

  async function copyConfig() {
    try {
      await navigator.clipboard.writeText(configText);
      open?.({
        type: "success",
        message: t("account.mcp.title"),
        description: t("account.mcp.copy.success"),
      });
    } catch {
      open?.({
        type: "error",
        message: t("account.mcp.title"),
        description: t("account.mcp.copy.error"),
      });
    }
  }

  return (
    <Stack gap="sm">
      <SectionHeader
        title={t("account.mcp.title")}
        description={t("account.mcp.description")}
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
      <Text size="sm">{t("account.mcp.authHint")}</Text>
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
