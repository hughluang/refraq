"use client";

import { Badge, Button, Code, Group, Stack, Text, Textarea, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import type { McpArgumentIssue } from "@/features/mcp/mcp-arguments";
import type { McpCallPart, McpListedTool, McpStoredCallOutcome } from "@/features/mcp/mcp-tools-list";
import { useMcpWorkspace } from "@/features/mcp/McpWorkspaceProvider";

export function schemaText(schema: unknown, missing: string): string {
  if (schema === null || schema === undefined) return missing;
  return JSON.stringify(schema, null, 2);
}

function formatIssue(issue: McpArgumentIssue, t: (key: string) => string): string {
  const schema = t("mcp.invoke.schema");
  switch (issue.kind) {
    case "empty":
      return t("mcp.invoke.empty");
    case "json":
      return `${t("mcp.invoke.invalidJson")} ${issue.reason}`;
    case "type":
      return `${schema} ${issue.path} ${t("mcp.invoke.mustBe")} ${issue.expected}.`;
    case "enum":
      return `${schema} ${issue.path} ${t("mcp.invoke.enum")} ${issue.values}.`;
    case "required":
      return `${schema} ${issue.path} ${t("mcp.invoke.required")}`;
    case "additional":
      return `${schema} ${issue.path} ${t("mcp.invoke.additional")}`;
    case "minimum":
      return `${schema} ${issue.path} ${t("mcp.invoke.atLeast")} ${issue.limit}.`;
    case "maximum":
      return `${schema} ${issue.path} ${t("mcp.invoke.atMost")} ${issue.limit}.`;
    case "minLength":
      return `${schema} ${issue.path} ${t("mcp.invoke.minLength")} ${issue.limit}.`;
    case "maxLength":
      return `${schema} ${issue.path} ${t("mcp.invoke.maxLength")} ${issue.limit}.`;
    case "minItems":
      return `${schema} ${issue.path} ${t("mcp.invoke.minItems")} ${issue.limit}.`;
    case "maxItems":
      return `${schema} ${issue.path} ${t("mcp.invoke.maxItems")} ${issue.limit}.`;
    case "pattern":
      return `${schema} ${issue.path} ${t("mcp.invoke.pattern")} ${issue.pattern}.`;
  }
}

function Parts({ parts }: { parts: McpCallPart[] }) {
  const t = useTranslate();
  return parts.map((part, index) =>
    part.kind === "json" ? (
      <section key={index} role="region" aria-label={t("mcp.invoke.decoded")}>
        <Text>{t("mcp.invoke.decoded")}</Text>
        <Code block>{JSON.stringify(part.value, null, 2)}</Code>
      </section>
    ) : (
      <section key={index} role="region" aria-label={t("mcp.invoke.text")}>
        <Text>{t("mcp.invoke.text")}</Text>
        <Text>{part.text}</Text>
      </section>
    ),
  );
}

function outcomeLabel(outcome: McpStoredCallOutcome, t: (key: string) => string): string {
  switch (outcome.status) {
    case "http":
      return t("mcp.invoke.http");
    case "transport":
      return t("mcp.invoke.transport");
    case "protocol":
      return t("mcp.invoke.protocol");
    case "sdk":
      return t("mcp.invoke.sdk");
    case "domain":
      return t("mcp.invoke.domain");
    case "result":
      return t("mcp.invoke.result");
    case "unknown":
      return t("mcp.invoke.unknown");
    case "stopped":
      return t("mcp.invoke.waitingStopped");
  }
}

function OutcomeView({
  outcome,
  submittedArguments,
}: {
  outcome: McpStoredCallOutcome;
  submittedArguments: string | null;
}) {
  const t = useTranslate();
  const label = outcomeLabel(outcome, t);
  const parts = outcome.status === "sdk" || outcome.status === "domain" || outcome.status === "result"
    ? outcome.parts
    : null;
  const protocol =
    outcome.status === "protocol"
      ? outcome.error
      : outcome.status === "sdk" || outcome.status === "domain" || outcome.status === "result"
        ? outcome.protocol
        : undefined;
  return (
    <div role="region" aria-live="polite" aria-label={label} style={{ overflow: "auto", maxHeight: "24rem" }}>
      {outcome.status === "unknown" && outcome.requestedCancellation ? (
        <Text>{t("mcp.invoke.cancellationRequested")}</Text>
      ) : null}
      <Text>{label}</Text>
      {submittedArguments ? (
        <section role="region" aria-label={t("mcp.invoke.sentArguments")}>
          <Text>{t("mcp.invoke.sentArguments")}</Text>
          <Code block>{submittedArguments}</Code>
        </section>
      ) : null}
      {parts ? <Parts parts={parts} /> : null}
      {protocol !== undefined ? (
        <section role="region" aria-label={t("mcp.invoke.protocolPayload")}>
          <Text>{t("mcp.invoke.protocolPayload")}</Text>
          <Code block>{JSON.stringify(protocol, null, 2)}</Code>
        </section>
      ) : null}
    </div>
  );
}

export function McpInvoke({ endpoint, tools }: { endpoint: string; tools: McpListedTool[] }) {
  const t = useTranslate();
  const [schemaOpenFor, setSchemaOpenFor] = useState<string | null>(null);
  const {
    invocation,
    setArgumentsText,
    runSelected,
    writeConfirm,
    beginWrite,
    confirmWrite,
    dismissWrite,
    callWait,
    stopWaiting,
  } = useMcpWorkspace();
  if (!invocation || invocation.endpoint !== endpoint) return null;
  const tool = tools.find((item) => item.name === invocation.toolName);
  if (!tool) return null;
  const qualified = `${endpoint} ${tool.name}`;
  const callWaiting = callWait?.endpoint === endpoint && callWait.toolName === tool.name;
  const runnable = tool.execution === "read" || tool.execution === "write";
  return (
    <Stack gap="xs">
      <div role="region" aria-label={`${t("mcp.invoke.argumentsFor")} ${qualified}`}>
        <Stack gap="xs">
          <Title order={3}>{t("mcp.invoke.selected")}</Title>
          <Group wrap="wrap"><Text ff="monospace" fw={500} style={{ overflowWrap: "anywhere" }}>{qualified}</Text><Badge variant="light">{runnable ? t(`mcp.execution.${tool.execution}`) : t("mcp.discovery.executionMissing")}</Badge></Group>
          <Text size="sm">{tool.description}</Text>
          <details open={schemaOpenFor === qualified}>
            <summary onClick={(event) => { event.preventDefault(); setSchemaOpenFor(schemaOpenFor === qualified ? null : qualified); }}>{t("mcp.invoke.schemaDisclosure")}</summary>
            {schemaOpenFor === qualified ? <Code block style={{ maxWidth: "100%", overflowX: "auto" }}>{schemaText(tool.inputSchema, t("mcp.discovery.schemaMissing"))}</Code> : null}
          </details>
          <Textarea
            label={t("mcp.invoke.arguments")}
            value={invocation.argumentsText}
            onChange={(event) => setArgumentsText(event.currentTarget.value)}
            rows={6}
            error={invocation.localError ? <span aria-live="polite">{formatIssue(invocation.localError, t)}</span> : undefined}
          />
          {callWaiting ? <Text aria-live="polite">{t("mcp.invoke.pending")}</Text> : null}
          {tool.execution === "read" ? (
            <Button type="button" loading={callWaiting} disabled={callWaiting} onClick={() => void runSelected(endpoint, tool.name, invocation.argumentsText)}>
              {`${t("mcp.invoke.run")} ${qualified}`}
            </Button>
          ) : null}
          {tool.execution === "write" ? (
            <Button type="button" onClick={() => beginWrite(endpoint, tool.name, invocation.argumentsText)}>
              {`${t("mcp.invoke.run")} ${qualified}`}
            </Button>
          ) : null}
          {callWaiting && !writeConfirm?.sending ? (
            <Button type="button" variant="default" onClick={() => stopWaiting("call")}>
              {t("mcp.invoke.stop")}
            </Button>
          ) : null}
          {runnable ? <Text>{t("mcp.invoke.serverRecord")}</Text> : null}
        </Stack>
      </div>
      {invocation.outcome ? (
        <OutcomeView
          outcome={invocation.outcome}
          submittedArguments={invocation.submittedArguments}
        />
      ) : null}
      {writeConfirm ? (
        <ConfirmActionModal
          opened
          onClose={dismissWrite}
          title={t("mcp.invoke.writeConfirm.title")}
          body={t("mcp.invoke.writeConfirm.notice")}
          confirmLabel={t("common.confirm")}
          cancelDisabled={false}
          loading={writeConfirm.sending}
          onConfirm={() => void confirmWrite()}
        >
          <Text>{`${t("mcp.invoke.writeConfirm.endpoint")} ${writeConfirm.endpoint}`}</Text>
          <Text>{`${t("mcp.invoke.writeConfirm.user")} ${writeConfirm.userId}`}</Text>
          <Text>{`${t("mcp.invoke.writeConfirm.tool")} ${writeConfirm.toolName}`}</Text>
          <Code block>{writeConfirm.argumentsJson}</Code>
          {writeConfirm.sending ? (
            <Button type="button" variant="default" onClick={() => stopWaiting("call")}>
              {t("mcp.invoke.stop")}
            </Button>
          ) : null}
        </ConfirmActionModal>
      ) : null}
    </Stack>
  );
}
