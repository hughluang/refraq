"use client";

import { Badge, Button, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect } from "react";

import { McpInvoke } from "@/features/mcp/McpInvoke";
import { useMcpWorkspace } from "@/features/mcp/McpWorkspaceProvider";

export function McpDiscovery({ endpoint }: { endpoint: string }) {
  const t = useTranslate();
  const { outcome, discoveryByEndpoint, discover, noteDetailEndpoint, selectTool, invocation, discoverWait, stopWaiting } = useMcpWorkspace();
  useEffect(() => { noteDetailEndpoint(endpoint); }, [endpoint, noteDetailEndpoint]);
  if (outcome.status !== "verified") return <Text size="sm" c="dimmed">{t("mcp.discovery.gate")}</Text>;
  const discovery = discoveryByEndpoint[endpoint] ?? { status: "idle" as const };
  const pending = discoverWait === endpoint;

  return (
    <Stack gap="sm" miw={0}>
      <Title order={3}>{t("mcp.discovery.title")}</Title>
      <Group wrap="wrap">
        <Button type="button" loading={pending} disabled={pending} onClick={() => void discover(endpoint)}>{t("mcp.discovery.action")}</Button>
        {pending ? <Button type="button" variant="default" onClick={() => stopWaiting("discover")}>{t("mcp.invoke.stop")}</Button> : null}
      </Group>
      <div aria-live="polite">
        {pending ? <Text>{t("mcp.discovery.pending")}</Text> : null}
        {discovery.status === "stopped" ? <Text>{t("mcp.invoke.waitingStopped")}</Text> : null}
        {discovery.status === "empty" ? <Text>{t("mcp.discovery.empty")}</Text> : null}
        {discovery.status === "unavailable" ? <Text>{t("mcp.discovery.unavailable")}</Text> : null}
        {discovery.status === "protocol-error" ? <Text>{t("mcp.discovery.protocolError")}</Text> : null}
        {discovery.status === "transport-failure" ? <Text>{t("mcp.discovery.transportFailure")}</Text> : null}
      </div>
      {discovery.status === "ready" ? <>
        <Stack component="ul" gap="sm" m={0} pl={0} style={{ listStyle: "none" }}>
          {discovery.tools.map((tool) => {
            const qualified = `${endpoint} ${tool.name}`;
            const selected = invocation?.endpoint === endpoint && invocation.toolName === tool.name;
            return <Stack component="li" key={qualified} aria-label={qualified} gap={4} p="sm" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
              <Group justify="space-between" wrap="wrap" gap="sm">
                <Group gap="sm" wrap="wrap">
                  <Text ff="monospace" fw={500} size="sm" style={{ overflowWrap: "anywhere" }}>{tool.name}</Text>
                  <Badge variant="light">{tool.execution === "read" || tool.execution === "write" ? t(`mcp.execution.${tool.execution}`) : t("mcp.discovery.executionMissing")}</Badge>
                </Group>
                <Button type="button" size="xs" variant={selected ? "light" : "default"} aria-pressed={selected} onClick={() => selectTool(endpoint, tool.name)}>{`${t("mcp.invoke.select")} ${qualified}`}</Button>
              </Group>
              <Text size="sm">{tool.description}</Text>
            </Stack>;
          })}
        </Stack>
        <McpInvoke endpoint={endpoint} tools={discovery.tools} />
      </> : null}
    </Stack>
  );
}
