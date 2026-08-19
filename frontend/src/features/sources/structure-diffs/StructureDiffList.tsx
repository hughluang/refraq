"use client";

import { Button, Group, Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback } from "react";

import { ListTable } from "@/components/display/ListTable";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { listStructureDiffs } from "@/features/sources/api";
import { StructureDiffClassBadge } from "@/features/sources/structure-diffs/StructureDiffClassBadge";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { usePagedList } from "@/hooks/usePagedList";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

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
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const { data: canShow, isLoading: canLoading } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.show,
  });

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback(
    (query: PageQuery) => listStructureDiffs(sourceId, query),
    [sourceId],
  );

  const { items, total, page, setPage, loading, error, reload, pageSize } =
    usePagedList({
      pageSize: PAGE_SIZE,
      fetch: fetchPage,
      resetDeps: [sourceId],
      onError,
    });
  const listPresentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: items.length,
    filtered: false,
  });

  const aclPending = canLoading || canShow === undefined;

  if (!aclPending && canShow && !canShow.can) {
    return <ForbiddenState reason={canShow.reason} />;
  }

  const title = `${t("structureDiffs.title")} · ${sourceId}`;

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
            onClick={() => void reload()}
          >
            {t("jobs.refresh")}
          </Button>
        </Group>
      }
    >
      {aclPending ? (
        <PageBodySkeleton />
      ) : (
        <ListTable
          state={listPresentation.state}
          columnCount={5}
          refreshing={listPresentation.refreshing}
          errorMessage={error}
          onRetry={() => void reload()}
          emptyMessage={t("structureDiffs.empty")}
          head={
            <Table.Tr>
              <Table.Th>{t("structureDiffs.fields.class")}</Table.Th>
              <Table.Th>{t("structureDiffs.fields.created")}</Table.Th>
              <Table.Th>{t("structureDiffs.fields.job")}</Table.Th>
              <Table.Th>{t("structureDiffs.fields.counts")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          }
          page={page}
          pageSize={pageSize}
          total={total}
          onPageChange={setPage}
        >
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
        </ListTable>
      )}
    </PageChrome>
  );
}
