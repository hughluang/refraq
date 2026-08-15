"use client";

import {
  Accordion,
  Button,
  Group,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { getStructureDiff } from "@/features/sources/api";
import { StructureDiffClassBadge } from "@/features/sources/structure-diffs/StructureDiffClassBadge";
import {
  COUNT_ORDER,
  groupChanges,
} from "@/features/sources/structure-diffs/groupChanges";
import type { StructureDiff } from "@/features/sources/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";

type Props = {
  sourceId: string;
  diffId: string;
};

function extraLabel(change: Record<string, unknown>): string | null {
  const parts: string[] = [];
  if ("from" in change || "to" in change) {
    parts.push(`${formatValue(change.from)} → ${formatValue(change.to)}`);
  }
  if (typeof change.name === "string" && change.name) {
    parts.push(change.name);
  }
  return parts.length ? parts.join(" · ") : null;
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (Array.isArray(value)) return value.join(", ") || "—";
  return String(value);
}

export function StructureDiffDetail({ sourceId, diffId }: Props) {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const { data: canShow, isLoading: canLoading } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.show,
  });

  const [diff, setDiff] = useState<StructureDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [jobOpened, setJobOpened] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const diffRes = await getStructureDiff(diffId);
      if (diffRes.structure_diff.source_id !== sourceId) {
        setError(t("structureDiffs.sourceMismatch"));
        setDiff(null);
        return;
      }
      setDiff(diffRes.structure_diff);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
      setDiff(null);
    } finally {
      setLoading(false);
    }
  }, [sourceId, diffId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => groupChanges(diff?.changes), [diff?.changes]);

  if (canLoading || canShow === undefined) return <PageLoader />;
  if (!canShow.can) return <ForbiddenState reason={canShow.reason} />;
  if (loading) return <PageLoader />;
  if (error) return <PageError message={error} />;
  if (!diff) return null;

  const title = `${t("structureDiffs.detailTitle")} · ${sourceId}`;

  return (
    <PageChrome
      title={title}
      description={t("structureDiffs.detailDescription")}
      actions={
        <Group gap="xs">
          <Button
            component={Link}
            href={`/console/sources/${sourceId}/structure-diffs`}
            variant="default"
            size="sm"
          >
            {t("structureDiffs.backToList")}
          </Button>
          <Button size="sm" variant="light" onClick={() => void load()}>
            {t("jobs.refresh")}
          </Button>
        </Group>
      }
    >
      <Stack gap="md">
        <Group gap="sm" wrap="wrap">
          <StructureDiffClassBadge value={diff.class} />
          <Text size="sm" ff="monospace">
            {diff.id}
          </Text>
          <Text size="sm" c="dimmed">
            {formatInstant(diff.created_at)}
          </Text>
          <Button
            size="compact-xs"
            variant="light"
            onClick={() => setJobOpened(true)}
          >
            {t("structureDiffs.openJob")}: {diff.job_id}
          </Button>
        </Group>

        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("structureDiffs.fields.countKey")}</Table.Th>
              <Table.Th>{t("structureDiffs.fields.countValue")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {COUNT_ORDER.map((key) => {
              const value = diff.counts?.[key] ?? 0;
              return (
                <Table.Tr key={key}>
                  <Table.Td>
                    {t(`structureDiffs.counts.${key}`)}
                  </Table.Td>
                  <Table.Td>
                    <Text c={value > 0 ? undefined : "dimmed"}>{value}</Text>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>

        {groups.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("structureDiffs.noChanges")}
          </Text>
        ) : (
          <Accordion multiple defaultValue={groups.map((g) => g.change)}>
            {groups.map((group) => (
              <Accordion.Item key={group.change} value={group.change}>
                <Accordion.Control>
                  {t(`structureDiffs.change.${group.change}`)} ({group.items.length})
                </Accordion.Control>
                <Accordion.Panel>
                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>
                          {t("structureDiffs.fields.locator")}
                        </Table.Th>
                        <Table.Th>
                          {t("structureDiffs.fields.detail")}
                        </Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {group.items.map((item, index) => (
                        <Table.Tr key={`${item.locator_key}-${index}`}>
                          <Table.Td>
                            <Text size="sm" ff="monospace">
                              {item.locator_key}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            <Text size="sm" c="dimmed">
                              {extraLabel(item) ?? "—"}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        )}
      </Stack>

      <JobDetailModal
        jobId={jobOpened ? diff.job_id : null}
        opened={jobOpened}
        onClose={() => setJobOpened(false)}
      />
    </PageChrome>
  );
}
