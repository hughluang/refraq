"use client";

import { Button, Group, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useCallback, useState } from "react";

import { JobReference } from "@/components/display/JobReference";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { PageChrome } from "@/components/layout/PageChrome";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { listStructureDiffs } from "@/features/sources/api/structure-diffs";
import { StructureDiffClassBadge } from "@/features/sources/structure-diffs/StructureDiffClassBadge";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useSourceName } from "@/features/sources/structure-diffs/useSourceName";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
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
  const formatInstant = useFormatInstant();
  const { push } = useConsoleNavigation();
  const [jobId, setJobId] = useState<string | null>(null);
  const query = useListQuery({ search: false });

  const fetchPage = useCallback(
    (query: PageQuery) => listStructureDiffs(sourceId, query),
    [sourceId],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [sourceId],
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, loading, reload } = list;
  const sourceName = useSourceName(sourceId);
  const title = sourceName.name
    ? `${t("structureDiffs.title")} · ${sourceName.name}`
    : t("structureDiffs.title");

  return (
    <PageChrome
      title={title}
      description={
        sourceName.failed ? t("common.error.loadFailed") : t("structureDiffs.description")
      }
      actions={
        <Group gap="xs">
          <Button
            component={ConsoleLink}
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
            onClick={() => void reload()}
          >
            {t("jobs.refresh")}
          </Button>
        </Group>
      }
    >
      <ListTable
          list={list}
          columnCount={5}
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
        >
          {items.map((diff) => {
            const href = `/console/sources/${sourceId}/structure-diffs/${diff.id}`;
            return (
            <Table.Tr key={diff.id}>
              <Table.Td>
                <StructureDiffClassBadge value={diff.class} />
              </Table.Td>
              <Table.Td>
                <RecordReference
                  name={formatInstant(diff.created_at)}
                  recordKey={diff.id}
                  href={href}
                />
              </Table.Td>
              <Table.Td>
                <JobReference
                  jobId={diff.job_id}
                  kind="structure"
                  status="succeeded"
                  onOpen={setJobId}
                />
              </Table.Td>
              <Table.Td>
                <Text size="xs">{nonzeroCounts(diff.counts)}</Text>
              </Table.Td>
              <Table.Td>
                <RowActions
                  recordName={diff.id}
                  verbs={[
                    {
                      key: "view",
                      label: t("structureDiffs.view"),
                      safety: "immediate",
                      onClick: () => push(href),
                    },
                  ]}
                />
              </Table.Td>
            </Table.Tr>
            );
          })}
        </ListTable>
      <JobDetailModal
        jobId={jobId}
        opened={jobId != null}
        onClose={() => setJobId(null)}
      />
    </PageChrome>
  );
}
