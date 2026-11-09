"use client";

import { Button, Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect } from "react";

import { useMcpWorkspace } from "@/features/mcp/McpWorkspaceProvider";

function schemaText(schema: unknown, missing: string): string {
  if (schema === null || schema === undefined) return missing;
  return JSON.stringify(schema, null, 2);
}

export function McpDiscovery({ endpoint }: { endpoint: string }) {
  const t = useTranslate();
  const { outcome, discoveryByEndpoint, discover, noteDetailEndpoint } = useMcpWorkspace();
  useEffect(() => {
    noteDetailEndpoint(endpoint);
  }, [endpoint, noteDetailEndpoint]);
  if (outcome.status !== "verified") return null;
  const discovery = discoveryByEndpoint[endpoint] ?? { status: "idle" as const };

  return (
    <Stack gap="xs">
      <Button type="button" onClick={() => void discover(endpoint)}>
        {t("mcp.discovery.action")}
      </Button>
      {discovery.status === "empty" ? <Text>{t("mcp.discovery.empty")}</Text> : null}
      {discovery.status === "unavailable" ? <Text>{t("mcp.discovery.unavailable")}</Text> : null}
      {discovery.status === "protocol-error" ? <Text>{t("mcp.discovery.protocolError")}</Text> : null}
      {discovery.status === "transport-failure" ? (
        <Text>{t("mcp.discovery.transportFailure")}</Text>
      ) : null}
      {discovery.status === "ready" ? (
        <ul>
          {discovery.tools.map((tool) => {
            const qualified = `${endpoint} ${tool.name}`;
            return (
              <li key={qualified} aria-label={qualified}>
                <Text>{qualified}</Text>
                <Text>{tool.description}</Text>
                <Text>{tool.execution ?? t("mcp.discovery.executionMissing")}</Text>
                <Code block>{schemaText(tool.inputSchema, t("mcp.discovery.schemaMissing"))}</Code>
              </li>
            );
          })}
        </ul>
      ) : null}
    </Stack>
  );
}
