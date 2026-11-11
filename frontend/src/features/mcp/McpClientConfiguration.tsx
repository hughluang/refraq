"use client";

import { Badge, Button, Code, Group, Stack, Text, Title, UnstyledButton } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { StatusBadge } from "@/components/display/StatusBadge";
import { FormSection } from "@/components/form/FormSection";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import {
  ENTITY_MCP_PUBLIC_PATH,
  mcpCatalogPath,
  mcpClientConfig,
  type McpCatalog,
  type McpCatalogTool,
} from "@/features/mcp/mcp-api";
import { apiClient } from "@/lib/api";
import { copyText } from "@/lib/copy-text";

export function McpClientConfiguration({ publicPath }: { publicPath: string }) {
  const t = useTranslate();
  const { open } = useNotification();
  const [origin, setOrigin] = useState("");
  const [tools, setTools] = useState<McpCatalogTool[] | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => { setOrigin(window.location.origin); }, []);
  useEffect(() => {
    let cancelled = false;
    setTools(null);
    setCatalogFailed(false);
    void apiClient<McpCatalog>(mcpCatalogPath(publicPath))
      .then((data) => {
        if (cancelled) return;
        if (!data || !Array.isArray(data.tools)) throw new Error("Invalid catalog");
        setTools(data.tools);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setCatalogFailed(true);
        presentProblemNotification(t, error, { onRetry: () => {
          if (!cancelled) setAttempt((value) => value + 1);
        } });
      });
    return () => { cancelled = true; };
  }, [publicPath, attempt]);

  async function copy(value: string) {
    try {
      await copyText(value);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  }

  const url = origin ? `${origin}${publicPath}` : "";
  const configuration = origin ? mcpClientConfig(origin, publicPath) : "";
  return (
    <FormSection title={t("mcp.connection.title")} columns={1}>
      <Stack gap="md" miw={0}>
        <DisplayField label={t("mcp.connection.url")} value={
          <Group gap="sm" wrap="wrap">
            <Text ff="monospace" size="sm" style={{ overflowWrap: "anywhere" }}>{url}</Text>
            <Button size="xs" variant="default" disabled={!url} onClick={() => void copy(url)}>{t("mcp.copy.url")}</Button>
          </Group>
        } />
        <DisplayField label={t("mcp.connection.transport")} value="Streamable HTTP · 2026-07-28" />
        <DisplayField label={t("mcp.connection.authorization")} value={t("mcp.connection.bearer")} />
        <Text size="sm">{t(publicPath === ENTITY_MCP_PUBLIC_PATH ? "mcp.entity.access" : "mcp.metadata.character")}</Text>
        <Stack gap="xs" miw={0}>
          <Group justify="space-between" wrap="wrap">
            <Text fw={500} size="sm">{t("mcp.connection.config")}</Text>
            <Button size="xs" variant="default" disabled={!configuration} onClick={() => void copy(configuration)}>{t("mcp.copy.config")}</Button>
          </Group>
          {configuration ? <Code block style={{ maxWidth: "100%", overflowX: "auto" }}>{configuration}</Code> : null}
          <Text size="sm" c="dimmed">{t("mcp.connection.placeholder")}</Text>
          <Text size="sm">{t("mcp.patHandoff")}</Text>
          <ConsoleLink href="/console/account">{t("mcp.openAccount")}</ConsoleLink>
        </Stack>
        <Stack gap="sm" aria-busy={tools === null && !catalogFailed}>
          <Title order={3}>{t("mcp.catalog.session")}</Title>
          <Text size="sm">{t(publicPath === ENTITY_MCP_PUBLIC_PATH ? "mcp.entity.catalogNote" : "mcp.metadata.catalogNote")}</Text>
          <Text size="sm" c="dimmed">{t("mcp.catalog.region")}</Text>
          <div aria-live="polite">
            {tools === null && !catalogFailed ? <Text size="sm">{t("mcp.catalog.loading")}</Text> : null}
            {tools?.length === 0 ? <Text size="sm">{t("mcp.catalog.empty")}</Text> : null}
            {catalogFailed ? <UnstyledButton type="button" onClick={() => setAttempt((value) => value + 1)}><StatusBadge tone="danger" labelKey="status.unloaded" /></UnstyledButton> : null}
          </div>
          {tools && tools.length > 0 ? <Stack component="ul" gap="sm" m={0} pl={0} style={{ listStyle: "none" }}>
            {tools.map((tool) => <Stack component="li" key={tool.name} gap={4} p="sm" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
              <Group gap="sm" wrap="wrap">
                <Text ff="monospace" fw={500} size="sm" style={{ overflowWrap: "anywhere" }}>{tool.name}</Text>
                <Badge variant="light">{tool.execution === "read" || tool.execution === "write" ? t(`mcp.execution.${tool.execution}`) : t("mcp.discovery.executionMissing")}</Badge>
              </Group>
              <Text size="sm">{tool.description}</Text>
              <Text size="xs" c="dimmed">{t("mcp.tool.permission")}: <Text component="span" inherit ff="monospace">{tool.permission}</Text></Text>
            </Stack>)}
          </Stack> : null}
        </Stack>
      </Stack>
    </FormSection>
  );
}
