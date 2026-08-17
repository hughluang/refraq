"use client";

import { Button, Group, Pagination, Table, Text } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { listStructureDiffs } from "@/features/sources/api";
import { StructureDiffClassBadge } from "@/features/sources/structure-diffs/StructureDiffClassBadge";
import type { StructureDiff } from "@/features/sources/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";

const PAGE_SIZE = 50;

type Props = {
  sourceId: string;
};

function nonzeroCounts(counts: Record<string, number> | undefined): string {
  if (!counts) return "—";
  const parts = Object.entries(counts)
    .filter(([, n]) => typeof n === "number" && n > 0)
    .map(([key, n]) => `${key} ${n}`);
  return parts.length ? parts.join(" · ") : "—";
}

export function StructureDiffList({ sourceId }: Props) {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const { data: canShow, isLoading: canLoading } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.show,
  });

  const [items, setItems] = useState<StructureDiff[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const listRes = await listStructureDiffs(sourceId, {
        limit: PAGE_SIZE,
        offset,
      });
      setItems(listRes.items);
      setTotal(listRes.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [sourceId, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const aclPending = canLoading || canShow === undefined;

  if (!aclPending && canShow && !canShow.can) {
    return <ForbiddenState reason={canShow.reason} />;
  }

  const title = `${t("structureDiffs.title")} · ${sourceId}`;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const showSkeleton = aclPending || loading;

  return (
    <PageChrome
      title={title}
      description={t("structureDiffs.description")}
      actions={
        <Group gap="xs">
          <Button
            component={Link}
            href="/console/sources"
            variant="default"
            size="sm"
          >
            {t("structureDiffs.backToSources")}
          </Button>
          <Button
            size="sm"
            variant="light"
            loading={loading}
            disabled={aclPending}
            onClick={() => void load()}
          >
            {t("jobs.refresh")}
          </Button>
        </Group>
      }
    >
      {showSkeleton ? (
        <PageBodySkeleton />
      ) : error ? (
        <PageError message={error} onRetry={() => void load()} />
      ) : items.length === 0 ? (
        <EmptyState message={t("structureDiffs.empty")} />
      ) : (
        <>
          <Table striped highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("structureDiffs.fields.class")}</Table.Th>
                <Table.Th>{t("structureDiffs.fields.created")}</Table.Th>
                <Table.Th>{t("structureDiffs.fields.job")}</Table.Th>
                <Table.Th>{t("structureDiffs.fields.counts")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((diff) => (
                <Table.Tr key={diff.id}>
                  <Table.Td>
                    <StructureDiffClassBadge value={diff.class} />
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatInstant(diff.created_at)}</Text>
                    <Text size="xs" c="dimmed" ff="monospace">
                      {diff.id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {diff.job_id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{nonzeroCounts(diff.counts)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      component={Link}
                      href={`/console/sources/${sourceId}/structure-diffs/${diff.id}`}
                      size="xs"
                      variant="light"
                    >
                      {t("structureDiffs.view")}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {pageCount > 1 ? (
            <Pagination
              mt="md"
              value={page}
              onChange={setPage}
              total={pageCount}
            />
          ) : null}
        </>
      )}
    </PageChrome>
  );
}
