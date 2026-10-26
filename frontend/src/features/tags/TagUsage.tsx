"use client";

import { Stack, Table } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive } from "@/components/display/statusTone";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { listChannels } from "@/features/channels/api";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { EntityStatusBadge } from "@/features/entities/EntityStatusBadge";
import { listEntities } from "@/features/entities/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

/** Names the caller can open. Counts stay on the Tag detail, which can be larger. */
export function TagUsage({ tagId }: { tagId: string }) {
  const { data: canEntities } = useCan({
    resource: ModuleId.entities,
    action: ModuleAction.list,
  });
  const { data: canChannels } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.list,
  });

  return (
    <Stack>
      {canEntities?.can ? <EntityUsage tagId={tagId} /> : null}
      {canChannels?.can ? <ChannelUsage tagId={tagId} /> : null}
    </Stack>
  );
}

function EntityUsage({ tagId }: { tagId: string }) {
  const t = useTranslate();
  const fetchPage = useCallback(
    (pageQuery: PageQuery) =>
      listEntities({
        tag_id: [tagId],
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

  return (
    <Stack gap="xs">
      <SectionHeader title={t("tags.usage.entities")} order={4} />
      <ListTable
        embedded
        list={list}
        columnCount={2}
        minWidth={480}
        emptyMessage={t("tags.usage.entitiesEmpty")}
        head={
          <Table.Tr>
            <Table.Th>{t("entities.fields.name")}</Table.Th>
            <Table.Th>{t("entities.fields.entityStatus")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference
                name={row.name}
                recordKey={row.table_name}
                href={`/console/entities/${row.id}`}
              />
            </Table.Td>
            <Table.Td>
              <EntityStatusBadge entity={row} />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </Stack>
  );
}

function ChannelUsage({ tagId }: { tagId: string }) {
  const t = useTranslate();
  const fetchPage = useCallback(
    (pageQuery: PageQuery) =>
      listChannels({
        tag_id: [tagId],
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

  return (
    <Stack gap="xs">
      <SectionHeader title={t("tags.usage.channels")} order={4} />
      <ListTable
        embedded
        list={list}
        columnCount={2}
        minWidth={480}
        emptyMessage={t("tags.usage.channelsEmpty")}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.fields.name")}</Table.Th>
            <Table.Th>{t("channels.fields.active")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => {
          const active = presentChannelActive(row.active);
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <RecordReference
                  name={row.name}
                  recordKey={row.id}
                  href={`/console/channels/${row.id}`}
                />
              </Table.Td>
              <Table.Td>
                <StatusBadge tone={active.tone} labelKey={active.labelKey} />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </Stack>
  );
}
