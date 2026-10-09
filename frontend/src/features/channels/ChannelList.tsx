"use client";

import { Anchor, Badge, Group, Table, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { listChannels } from "@/features/channels/api";
import { ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ChannelList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const [q, setQ] = useState("");
  const fetchPage = useCallback(
    (query: PageQuery) => listChannels({ q: q.trim() || undefined, ...query }),
    [q],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [q],
    filtered: q.trim() !== "",
  });

  return (
    <PageChrome
      title={t("channels.title")}
      description={t("channels.description")}
      actions={
        <CreateListAction resource={ModuleId.channels} href="/console/channels/new">
          {t("channels.create")}
        </CreateListAction>
      }
    >
      <Group>
        <TextInput
          placeholder={t("channels.search")}
          value={q}
          onChange={(event) => setQ(event.currentTarget.value)}
          w={280}
        />
      </Group>
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("channels.list.empty")}
        noMatchMessage={t("channels.list.noMatch")}
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
              <Anchor component={Link} href={`/console/channels/${channel.id}`}>
                {channel.name}
              </Anchor>
            </Table.Td>
            <Table.Td>
              <Badge variant="light" color={channel.active ? "green" : "gray"}>
                {channel.active ? t("form.value.yes") : t("form.value.no")}
              </Badge>
            </Table.Td>
            <Table.Td>
              {channel.latest_version ? channel.latest_version.number : "—"}
            </Table.Td>
            <Table.Td>{formatInstant(channel.updated_at)}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
