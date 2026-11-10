"use client";

import { Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import {
  ENTITY_MCP_PUBLIC_PATH,
  mcpCatalogPath,
  mcpClientConfig,
  type McpCatalog,
  type McpCatalogTool,
} from "@/features/mcp/mcp-api";
import { apiClient } from "@/lib/api";

export function McpClientConfiguration({ publicPath }: { publicPath: string }) {
  const t = useTranslate();
  const [origin, setOrigin] = useState("");
  const [tools, setTools] = useState<McpCatalogTool[] | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);

  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void apiClient<McpCatalog>(mcpCatalogPath(publicPath))
      .then((data) => {
        if (cancelled) return;
        if (!data || !Array.isArray(data.tools)) {
          setTools(null);
          setCatalogFailed(true);
          return;
        }
        setCatalogFailed(false);
        setTools(data.tools);
      })
      .catch(() => {
        if (!cancelled) {
          setTools(null);
          setCatalogFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [publicPath]);

  const url = origin ? `${origin}${publicPath}` : "";
  return (
    <Stack gap="xs">
      {url ? <Text>{url}</Text> : null}
      {url ? <Code block>{mcpClientConfig(origin, publicPath)}</Code> : null}
      <Text>{t("mcp.patHandoff")}</Text>
      <ConsoleLink href="/console/account">{t("mcp.openAccount")}</ConsoleLink>
      <Text>
        {t(
          publicPath === ENTITY_MCP_PUBLIC_PATH
            ? "mcp.entity.catalogNote"
            : "mcp.metadata.catalogNote",
        )}
      </Text>
      <Text>{t("mcp.troubleshoot.health")}</Text>
      <Text>{t("mcp.troubleshoot.protocol")}</Text>
      <Text>{t("mcp.troubleshoot.compatibility")}</Text>
      <Text>{t("mcp.catalog.region")}</Text>
      {tools && tools.length > 0 ? (
        <ul>
          {tools.map((tool) => (
            <li key={tool.name}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
                <span>{tool.name}</span>
                <span>{tool.permission}</span>
                <span>{tool.description}</span>
                {typeof tool.execution === "string" && tool.execution.length > 0 ? (
                  <span>{tool.execution}</span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {tools && tools.length === 0 ? <Text>{t("mcp.catalog.empty")}</Text> : null}
      {catalogFailed ? <Text>{t("mcp.catalog.failed")}</Text> : null}
    </Stack>
  );
}
