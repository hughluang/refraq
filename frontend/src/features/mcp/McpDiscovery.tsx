"use client";

import { Button, Code, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect } from "react";

import { McpInvoke, schemaText } from "@/features/mcp/McpInvoke";
import { useMcpWorkspace } from "@/features/mcp/McpWorkspaceProvider";

export function McpDiscovery({ endpoint }: { endpoint: string }) {
  const t = useTranslate();
  const { outcome, discoveryByEndpoint, discover, noteDetailEndpoint, selectTool, discoverWait, stopWaiting } =
    useMcpWorkspace();
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
      {discoverWait === endpoint ? (
        <Button type="button" onClick={() => stopWaiting("discover")}>
          {t("mcp.invoke.stop")}
        </Button>
      ) : null}
      {discovery.status === "stopped" ? <Text>{t("mcp.invoke.waitingStopped")}</Text> : null}
      {discovery.status === "empty" ? <Text>{t("mcp.discovery.empty")}</Text> : null}
      {discovery.status === "unavailable" ? <Text>{t("mcp.discovery.unavailable")}</Text> : null}
      {discovery.status === "protocol-error" ? <Text>{t("mcp.discovery.protocolError")}</Text> : null}
      {discovery.status === "transport-failure" ? (
        <Text>{t("mcp.discovery.transportFailure")}</Text>
      ) : null}
      {discovery.status === "ready" ? (
        <>
          <ul>
            {discovery.tools.map((tool) => {
              const qualified = `${endpoint} ${tool.name}`;
              return (
                <li key={qualified} aria-label={qualified}>
                  <Text>{qualified}</Text>
                  <Text>{tool.description}</Text>
                  <Text>{tool.execution ?? t("mcp.discovery.executionMissing")}</Text>
                  <Code block>{schemaText(tool.inputSchema, t("mcp.discovery.schemaMissing"))}</Code>
                  <Button type="button" onClick={() => selectTool(endpoint, tool.name)}>
                    {`${t("mcp.invoke.select")} ${qualified}`}
                  </Button>
                </li>
              );
            })}
          </ul>
          <McpInvoke endpoint={endpoint} tools={discovery.tools} />
        </>
      ) : null}
    </Stack>
  );
}
