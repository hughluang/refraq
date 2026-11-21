"use client";

import { Button, Group, Pagination, ScrollArea, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { ApiError } from "@/lib/api";
import { getExecutionOutput, getVersion, listExecutions } from "./api";
import { RunExecutionOutput } from "./RunExecutionOutput";
import type { ChannelRunDetail, GraphNode } from "./types";
import { isTerminalRun } from "./runSession";

const PAGE_SIZE = 100;

type ReadResult =
  | { state: "pending" | "unavailable" | "denied" | "absent" | "readFailed" }
  | { state: "rows"; table: string; source: string; rows: unknown[]; total: number; freshness: string };

export function RecordedTableRead({ channelId, detail, objectId, preferredNode }: {
  channelId: string; detail: ChannelRunDetail; objectId: string; preferredNode: string | null;
}) {
  const t = useTranslate();
  const nodes = detail.graph?.nodes.filter((node) => node.type === "read.mirror" && node.config.object_id === objectId) ?? [];
  const node = preferredNode === null
    ? (nodes.length === 1 ? nodes[0] : undefined)
    : nodes.find((item) => item.id === preferredNode);
  if (!node) return <Stack align="start">
    <Text>{t("channels.verify.removed")}</Text>
    <Button component={ConsoleLink} href={`/console/channels/${encodeURIComponent(channelId)}`}>{t("channels.verify.current")}</Button>
  </Stack>;
  const summary = detail.node_summaries.find((item) => item.node_id === node.id);
  return <RecordedReadPage key={JSON.stringify([channelId, detail.run.job_id, detail.run.version, node.id, summary, detail.run.status])}
    channelId={channelId} detail={detail} node={node} count={summary?.execution_count ?? 0} />;
}

function RecordedReadPage({ channelId, detail, node, count }: {
  channelId: string; detail: ChannelRunDetail; node: GraphNode; count: number;
}) {
  const t = useTranslate();
  const { job_id: jobId, version, status } = detail.run;
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<ReadResult>({ state: "pending" });
  const refresh = () => {
    setResult({ state: "pending" });
    setAttempt((prior) => prior + 1);
  };
  useEffect(() => {
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);
  useEffect(() => {
    let current = true;
    async function load(): Promise<ReadResult> {
      if (version == null || count === 0) return { state: isTerminalRun(status) ? "absent" : "pending" };
      const executions = await listExecutions(channelId, jobId, { node_id: node.id, limit: 1, offset: count - 1 });
      const execution = executions.items.find((item) => item.node_id === node.id);
      if (!execution || execution.status === "running") return { state: isTerminalRun(status) ? "absent" : "pending" };
      if (execution.error_code === "AUTH_FORBIDDEN") return { state: "denied" };
      if (execution.status !== "succeeded") return { state: execution.error_code === "MIRROR_READ_UNAVAILABLE" ? "readFailed" : "unavailable" };
      const [binding, records, freshness] = await Promise.all([
        getVersion(channelId, version),
        getExecutionOutput(channelId, jobId, execution.seq, { path: "rows", limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
        getExecutionOutput(channelId, jobId, execution.seq, { path: "freshness" }),
      ]);
      if (!("items" in records) || !Array.isArray(records.items) || typeof records.total !== "number") return { state: "unavailable" };
      const names = binding.version.mirror_bindings?.find((item) => item.object_id === node.config.object_id && item.node_ids.includes(node.id));
      const value = "value" in freshness ? freshness.value : null;
      const label = value && typeof value === "object" && "status" in value ? value.status : value;
      return { state: "rows", rows: records.items, total: records.total, freshness: typeof label === "string" ? label : "unknown",
        table: names?.qualified_table ?? "", source: names?.source_name ?? "" };
    }
    void load().then((value) => { if (current) setResult(value); }, (error: unknown) => {
      if (current) setResult({ state: error instanceof ApiError && [401, 403, 404].includes(error.status) ? "denied" : "unavailable" });
    });
    return () => { current = false; };
  }, [channelId, jobId, version, status, count, node.id, node.config.object_id, page, attempt]);
  const skipped = result.state === "rows" && result.total === 0 && result.freshness === "stale" && node.config.freshness_policy === "skip";
  return <ScrollArea style={{ flex: 1, minHeight: 0 }}><Stack gap="sm">
    <Group justify="space-between">
      <Text fw={600}>{t("channels.verify.output")}</Text>
      <Button size="xs" variant="default" onClick={refresh}>{t("common.refresh")}</Button>
    </Group>
    {result.state === "rows" ? <>
      <Text>{[result.source, result.table, node.name || node.ref || node.id].filter(Boolean).join(" / ")}</Text>
      {skipped ? <Text>{t("channels.verify.skipped")}</Text> : <>
        {result.freshness !== "ready" && <Text>{t(result.freshness === "stale" ? "channels.verify.stale" : "channels.verify.unknown")}</Text>}
        {result.total === 0 ? <Text>{t("channels.verify.empty")}</Text> : <>
          <RunExecutionOutput channelId={channelId} jobId={jobId} value={{ rows: result.rows }}
            totals={{ rows: result.total }} view={{ kind: "rows", rows: "rows", metrics: [] }} />
          {result.total > PAGE_SIZE && <Pagination total={Math.ceil(result.total / PAGE_SIZE)} value={page} onChange={(next) => {
            setResult({ state: "pending" });
            setPage(next);
          }} />}
        </>}
      </>}
    </> : <Text>{t(result.state === "readFailed" ? "channels.verify.unavailable" : `channels.verify.${result.state}`)}</Text>}
    {result.state === "readFailed" && node.config.freshness_policy === "fail" && <Text size="sm">{t("channels.verify.policy")}</Text>}
  </Stack></ScrollArea>;
}
