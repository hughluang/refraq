"use client";

import { Badge, Group, Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useMemo } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentChannelActive } from "@/components/display/statusTone";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { PageChrome } from "@/components/layout/PageChrome";
import { listChannels } from "@/features/channels/api";
import { ChannelListTagFilter } from "@/features/channels/ChannelListTagFilter";
import { channelListRequest } from "@/features/channels/channelListFilter";
import { ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;
const NO_TAG_IDS: readonly string[] = [];

export function ChannelList() {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const query = useListQuery({
    filters: [
      { key: "active", type: "select", defaultValue: "" },
      { key: "tag_id", type: "multi", defaultValue: NO_TAG_IDS },
    ],
  });
  const active = query.select("active");
  const tagIds = query.multi("tag_id");
  const fetchPage = useCallback(
    (page: PageQuery) =>
      listChannels(
        channelListRequest({
          q: query.search,
          active,
          tagIds,
          limit: page.limit,
          offset: page.offset,
        }),
      ),
    [active, query.search, tagIds],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, active, tagIds],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items } = list;
  const knownTags = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of items) {
      for (const tag of row.tags) names.set(tag.id, tag.name);
    }
    return names;
  }, [items]);

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
        <ListToolbar
          query={query}
          searchPlaceholder={t("channels.search")}
          filters={[
            {
              key: "active",
              label: t("channels.list.activation"),
              options: [
                { value: "true", label: t("channels.status.active") },
                { value: "false", label: t("channels.status.inactive") },
              ],
            },
          ]}
          extra={
            <ChannelListTagFilter
              value={tagIds}
              onChange={(ids) => query.setFilter("tag_id", ids)}
              known={knownTags}
            />
          }
        />
      }
    >
      <ListTable
        list={list}
        columnCount={5}
        emptyMessage={t("channels.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("channels.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("channels.fields.name")}</Table.Th>
            <Table.Th>{t("channels.fields.tags")}</Table.Th>
            <Table.Th>{t("channels.fields.active")}</Table.Th>
            <Table.Th>{t("channels.fields.latestVersion")}</Table.Th>
            <Table.Th>{t("channels.fields.updatedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {items.map((channel) => (
          <Table.Tr key={channel.id}>
            <Table.Td>
              <RecordReference
                name={channel.name}
                recordKey={channel.id}
                href={`/console/channels/${channel.id}`}
              />
            </Table.Td>
            <Table.Td>
              {channel.tags.length === 0 ? (
                "—"
              ) : (
                <Group gap={4} wrap="wrap">
                  {channel.tags.map((tag) => (
                    <Badge key={tag.id} size="sm" variant="light" color="gray">
                      {tag.name}
                    </Badge>
                  ))}
                </Group>
              )}
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
