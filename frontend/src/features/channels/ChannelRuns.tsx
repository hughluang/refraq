"use client";

import { Anchor, Button, Group, Select, Stack, Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useRef } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { LiveStatusAnnouncer } from "@/components/display/LiveStatusAnnouncer";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listRuns } from "@/features/channels/api";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { RUN_STATUS_VALUES, RUN_TARGET_VALUES, historyContext } from "@/features/channels/channelHistory";
import { copyText } from "@/lib/copy-text";
import { formatFailedNode, formatRunSubject, nodeDisplayName } from "@/features/channels/formatRunSubject";
import { formatRunError } from "@/features/channels/problemLabel";
import { isTerminalRun } from "@/features/channels/runSession";
import type { ChannelRun } from "@/features/channels/types";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { cancelJob } from "@/features/jobs/api";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useLiveStatus, type LiveRefreshResult } from "@/hooks/useLiveStatus";
import { useListQuery } from "@/hooks/useListQuery";
import { isSessionExpiredError } from "@/lib/api";
import { formatJobDuration } from "@/lib/datetime";
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";

const PAGE_SIZE = 50;
const FILTERS = [
  { key: "run_status", type: "select", defaultValue: "", accept: RUN_STATUS_VALUES },
  { key: "run_target", type: "select", defaultValue: "", accept: RUN_TARGET_VALUES },
] as const;

export function inboundRunLabel(
  run: Pick<ChannelRun, "trigger_kind" | "trigger_ref">,
  t: (key: string) => string,
): string | null {
  if (run.trigger_kind !== "inbound") return null;
  const kind = t("channels.runs.trigger.inbound");
  const path = run.trigger_ref?.trim() ?? "";
  return path ? `${kind} · ${path}` : kind;
}

export function ChannelRuns({ channelId, origin = "show" }: { channelId: string; origin?: "show" | "edit" }) {
  const { open } = useNotification();
  const t = useTranslate();
  const showInstant = useShowInstant();
  const query = useListQuery({ search: false, filters: FILTERS, pageKey: "run_page" });
  const status = query.select("run_status");
  const target = query.select("run_target");
  const { data: canWrite } = useCan({ resource: ModuleId.channels, action: ModuleAction.edit });
  const { data: canJobs } = useCan({ resource: ModuleId.jobs, action: ModuleAction.list });
  const canStop = Boolean(canWrite?.can || canJobs?.can);
  const stopRun = useConsoleMutation();
  const tRef = useRef(t);
  tRef.current = t;
  const unloadedNotice = useRef(false);
  const retryRef = useRef<() => Promise<void>>(async () => {});
  const reportRefreshFailure = (result: LiveRefreshResult) => {
    if (result.ok || isSessionExpiredError(result.error)) return;
    presentProblemNotification(tRef.current, result.error, { onRetry: () => void retryRef.current() });
  };
  const live = useLiveStatus({
    key: `${channelId}:${query.page}:${status}:${target}`,
    terminalIntervalMs: 30000,
    onRefreshResult: reportRefreshFailure,
    fetch: (signal) => listRuns(channelId, {
      ...(status ? { status } : {}),
      ...(target ? { target } : {}),
      limit: PAGE_SIZE,
      offset: pageToOffset(query.page, PAGE_SIZE),
    }, { signal }),
    isTerminal: (result) => result.items.every((run) => isTerminalRun(run.status)),
  });

  const items = live.data?.items ?? [];
  const total = live.data?.total ?? 0;
  const sessionExpired = isSessionExpiredError(live.error);
  const unloaded = live.data == null && live.stale && !sessionExpired;
  retryRef.current = () => live.refresh();
  const freshness = live.data != null && live.stale && !sessionExpired
    ? { updatedAt: live.lastSuccessAt, onRefresh: () => void retryRef.current() }
    : null;
  useEffect(() => {
    if (live.data || !live.stale || sessionExpired) {
      if (live.data || !live.stale) unloadedNotice.current = false;
      return;
    }
    if (unloadedNotice.current) return;
    unloadedNotice.current = true;
    presentProblemNotification(tRef.current, live.error, { onRetry: () => void retryRef.current() });
  }, [live.data, live.error, live.stale, sessionExpired]);
  const statusText = items.map((run) => `${showInstant(run.started_at ?? run.created_at)} ${t(presentJobStatus(run.status).labelKey)}`).join(", ");
  const list = {
    presentation: listPresentationOf({
      loading: live.loading || live.refreshing || (sessionExpired && live.data == null),
      error: unloaded ? "unloaded" : null,
      total,
      itemCount: items.length,
      filtered: query.isFiltered,
    }),
    reload: () => live.refresh(),
    page: query.page,
    setPage: query.setPage,
    pageSize: PAGE_SIZE,
    total,
  };

  return (
    <div className="channel-drawer-list channel-history">
      <LiveStatusAnnouncer text={statusText} />
      <SectionHeader order={2} title={t("channels.runs.history")} actions={
        <Button size="sm" variant="light" loading={live.refreshing} onClick={() => void live.refresh()}>{t("jobs.refresh")}</Button>
      } />
      <Group gap="sm" align="end" mb="sm">
        <Select label={t("jobs.fields.status")} value={status} onChange={(value) => query.setFilter("run_status", value ?? "")} data={[{ value: "", label: t("channels.runs.all") }, ...RUN_STATUS_VALUES.map((value) => ({ value, label: t(`status.job.${value}`) }))]} />
        <Select label={t("channels.runs.target")} value={target} onChange={(value) => query.setFilter("run_target", value ?? "")} data={[{ value: "", label: t("channels.runs.all") }, ...RUN_TARGET_VALUES.map((value) => ({ value, label: t(`channels.run.target.${value}`) }))]} />
        {query.isFiltered ? <Button variant="subtle" onClick={query.clear}>{t("common.filters.clear")}</Button> : null}
      </Group>
      <ListTable list={list} columnCount={1} minWidth={280} emptyMessage={t("channels.runs.empty")} onClearFilters={query.isFiltered ? query.clear : undefined}
        head={<Table.Tr><Table.Th scope="col"><div className="channel-history-row">
          <span>{t("channels.runs.started")}</span><span>{t("jobs.fields.status")}</span>
          <span>{t("channels.runs.target")} / {t("jobs.fields.trigger")}</span><span>{t("channels.run.column.error")}</span>
        </div></Table.Th></Table.Tr>}>
        {items.map((run) => {
          const presentation = presentJobStatus(run.status);
          const error = formatRunError(t, run.error_code, run.error_message);
          const errorDetail = error.detail && error.detail !== error.label ? error.detail : null;
          const nodes = run.nodes ?? [];
          const failedNode = run.status === "failed" ? formatFailedNode(nodes, run.failed_node_id) : null;
          const stoppedNode = run.status === "cancelled" ? nodeDisplayName(nodes, run.stopped_node_id) : null;
          const showError = run.status === "failed" || run.status === "cancelled";
          const trigger = run.trigger_kind === "retry" || run.trigger_kind === "error"
            ? `${t(`channels.runs.trigger.${run.trigger_kind}`)}${run.trigger_ref ? ` · ${run.trigger_ref}` : ""}`
            : inboundRunLabel(run, t) ?? formatJobTrigger(run, t);
          const name = showInstant(run.started_at ?? run.created_at);
          return (
            <Table.Tr key={run.job_id}><Table.Td style={{ overflowWrap: "anywhere" }}>
              <div className="channel-history-row">
                <Stack gap={4}>
                  <Text size="xs" c="dimmed">{t(run.started_at ? "channels.runs.started" : "jobs.fields.created")}</Text>
                  <Anchor component={ConsoleLink} href={`/console/channels/${channelId}/runs/${run.job_id}?${historyContext(`run_origin=${origin}&run_status=${status}&run_target=${target}&run_page=${query.page}`)}`} size="sm" aria-label={name}><Instant value={run.started_at ?? run.created_at} /></Anchor>
                  <Button variant="subtle" size="compact-xs" aria-label={t("channels.runs.copyId", { id: run.job_id })} onClick={() => {
                    void copyText(run.job_id).then(() => open?.({ type: "success", message: t("common.copy.success") }), () => open?.({ type: "error", message: t("common.copy.failed") }));
                  }}>{run.job_id}</Button>
                </Stack>
                <Stack gap={4}>
                  <StatusBadge size="xs" tone={presentation.tone} labelKey={presentation.labelKey} explanation={(run.error_code || run.error_message) && error.label ? error.label : null} freshness={freshness} />
                  <Text size="sm">{t("jobs.fields.duration")}: {formatJobDuration(run)}</Text>
                  {run.outcome ? <Text size="sm">{t(`channels.runs.outcome.${run.outcome}`)}</Text> : null}
                </Stack>
                <Stack gap={4}>
                  <Text size="sm" fw={500}>{formatRunSubject(run, t) || t("channels.runs.subject.unresolved")}{run.target === "draft" && run.draft_revision != null ? ` · ${t("channels.runs.revision", { number: run.draft_revision })}` : ""}</Text>
                  {run.stop_at_node_id ? <Text size="sm">{t("channels.runs.partial", { node: nodeDisplayName(nodes, run.stop_at_node_id) })}</Text> : null}
                  <Text size="sm">{t("jobs.fields.trigger")}: {trigger}</Text>
                  {run.ignore_checkpoints ? <Text size="xs" c="dimmed">{t("channels.runs.ignoreCheckpoints")}</Text> : null}
                </Stack>
                <Stack gap={4}>
                {failedNode ? <Text size="sm">{failedNode}</Text> : null}
                {stoppedNode ? <Text size="sm">{t("channels.runDetail.stoppedAt", { node: stoppedNode })}</Text> : null}
                {showError && error.label ? <Text size="sm">{error.label}</Text> : null}
                {showError && errorDetail ? <Text size="sm" c="dimmed">{errorDetail}</Text> : null}
                {!isTerminalRun(run.status) && canStop ? <div><Button type="button" size="xs" color="red" variant="light" loading={stopRun.isSubmitting(run.job_id)} onClick={() => stopRun.run({
                  key: run.job_id, safety: "confirm", recordName: name,
                  title: t("channels.run.stop.confirmTitle", { name }), consequence: t("channels.run.stop.consequence"),
                  confirmLabel: t("channels.run.stop"), confirmColor: "red", outcome: t("channels.run.stop.outcome"),
                  execute: () => cancelJob(run.job_id), onSuccess: () => live.refresh(),
                })}>{t("channels.run.stop")}</Button></div> : null}
                </Stack>
              </div>
            </Table.Td></Table.Tr>
          );
        })}
      </ListTable>
      {stopRun.dialog}
    </div>
  );
}
