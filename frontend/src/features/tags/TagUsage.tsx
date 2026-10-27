"use client";

import { Stack, Table } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive, presentEntityStatus } from "@/components/display/statusTone";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { entityStatus } from "@/features/entities/publishStatus";
import { listTagSubjects } from "@/features/tags/api";
import type { TagSubject } from "@/features/tags/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

/** Names the caller can open. Counts stay on the Tag resource, which can be larger. */
export function TagUsage({ tagId }: { tagId: string }) {
  const { data: canEntities } = useCan({
    resource: ModuleId.entities,
    action: ModuleAction.list,
  });
  const { data: canChannels } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.list,
  });
  if (!canEntities?.can && !canChannels?.can) return null;
  return (
    <SubjectUsage
      tagId={tagId}
      entities={Boolean(canEntities?.can)}
      channels={Boolean(canChannels?.can)}
    />
  );
}

function SubjectUsage({
  tagId,
  entities,
  channels,
}: {
  tagId: string;
  entities: boolean;
  channels: boolean;
}) {
  const t = useTranslate();
  const fetchPage = useCallback(
    (pageQuery: PageQuery) =>
      listTagSubjects(tagId, {
        limit: pageQuery.limit,
        offset: pageQuery.offset,
      }),
    [tagId],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [tagId],
  });
  const emptyMessage = entities && channels
    ? t("tags.usage.empty")
    : entities
      ? t("tags.usage.entitiesEmpty")
      : t("tags.usage.channelsEmpty");

  return (
    <Stack gap="xs">
      <SectionHeader title={t("tags.usage.title")} order={4} />
      <ListTable
        embedded
        list={list}
        columnCount={3}
        minWidth={480}
        emptyMessage={emptyMessage}
        head={
          <Table.Tr>
            <Table.Th>{t("tags.usage.kind")}</Table.Th>
            <Table.Th>{t("tags.usage.name")}</Table.Th>
            <Table.Th>{t("tags.usage.status")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={`${row.kind}:${row.id}`}>
            <Table.Td>{t(kindLabel(row))}</Table.Td>
            <Table.Td>
              <RecordReference
                name={row.name}
                recordKey={row.kind === "entity" ? row.table_name : row.id}
                href={
                  row.kind === "entity"
                    ? `/console/entities/${row.id}`
                    : `/console/channels/${row.id}`
                }
              />
            </Table.Td>
            <Table.Td>
              <SubjectStatus row={row} />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </Stack>
  );
}

function kindLabel(row: TagSubject): string {
  return row.kind === "entity" ? "tags.usage.kind.entity" : "tags.usage.kind.channel";
}

function SubjectStatus({ row }: { row: TagSubject }) {
  if (row.kind === "entity") {
    const presentation = presentEntityStatus(entityStatus(row));
    return <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} />;
  }
  const active = presentChannelActive(row.active);
  return <StatusBadge tone={active.tone} labelKey={active.labelKey} />;
}
