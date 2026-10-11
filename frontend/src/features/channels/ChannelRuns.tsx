"use client";

import { Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { EmptyState } from "@/components/feedback/EmptyState";
import { formatRunSubject } from "@/features/channels/formatRunSubject";
import { RunErrorText } from "@/features/channels/RunErrorText";
import { listRuns } from "@/features/channels/api";
import type { ChannelRun } from "@/features/channels/types";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";

export function ChannelRuns({ channelId }: { channelId: string }) {
  const t = useTranslate();
  const [items, setItems] = useState<ChannelRun[]>([]);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      void listRuns(channelId, { limit: 50 }).then((page) => {
        if (!cancelled) setItems(page.items);
      });
    };
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [channelId]);
  if (items.length === 0) return <EmptyState message={t("channels.runs.empty")} />;
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t("channels.runs.status")}</Table.Th>
          <Table.Th>{t("channels.runs.subject")}</Table.Th>
          <Table.Th>{t("channels.runs.trigger")}</Table.Th>
          <Table.Th>{t("channels.runs.started")}</Table.Th>
          <Table.Th>{t("channels.runs.error")}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {items.map((run) => (
          <Table.Tr key={run.job_id}>
            <Table.Td>
              <Link href={`/console/channels/${channelId}/runs/${run.job_id}`}>
                <JobStatusBadge status={run.status} />
              </Link>
            </Table.Td>
            <Table.Td>
              {formatRunSubject(run, t)}
              {run.ignore_checkpoints ? (
                <Text span size="xs" c="dimmed" ml={6}>
                  {t("channels.runs.ignoreCheckpoints")}
                </Text>
              ) : null}
            </Table.Td>
            <Table.Td>{formatJobTrigger(run, t)}</Table.Td>
            <Table.Td>
              <Instant value={run.started_at ?? run.created_at} />
            </Table.Td>
            <Table.Td>
              <RunErrorText
                code={run.error_code}
                message={run.error_message}
                empty="—"
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
