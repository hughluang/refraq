"use client";

import { Group, Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive } from "@/components/display/statusTone";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { PageChrome } from "@/components/layout/PageChrome";
import { listChannels } from "@/features/channels/api";
import { ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ChannelList() {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) =>
      listChannels({ q: query.search || undefined, ...page }),
    [query.search],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });

  const createAction = (
    <CreateListAction resource={ModuleId.channels} href="/console/channels/new">
      {t("channels.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("channels.title")}
      description={t("channels.description")}
      actions={createAction}
      toolbar={
        <ListToolbar query={query} searchPlaceholder={t("channels.search")} />
      }
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("channels.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("channels.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.fields.name")}</Table.Th>
            <Table.Th>{t("channels.fields.active")}</Table.Th>
            <Table.Th>{t("channels.fields.latestVersion")}</Table.Th>
            <Table.Th>{t("channels.fields.updatedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((channel) => (
          <Table.Tr key={channel.id}>
            <Table.Td>
              <RecordReference
                name={channel.name}
                recordKey={channel.id}
                href={`/console/channels/${channel.id}`}
              />
            </Table.Td>
            <Table.Td>
              <Group gap={6} wrap="nowrap">
                <StatusBadge
                  tone={presentChannelActive(channel.active).tone}
                  labelKey={presentChannelActive(channel.active).labelKey}
                />
                {channel.persistently_failing ? (
                  <StatusBadge tone="warning" labelKey="channels.persistentlyFailing" />
                ) : null}
              </Group>
            </Table.Td>
            <Table.Td>
              {channel.latest_version ? channel.latest_version.number : "—"}
            </Table.Td>
            <Table.Td>{showInstant(channel.updated_at)}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
