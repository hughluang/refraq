"use client";

import { Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { ListToolbar } from "@/components/display/ListToolbar";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { listTags } from "@/features/tags/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function TagList() {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const query = useListQuery();

  const fetchPage = useCallback(
    (page: PageQuery) =>
      listTags({
        q: query.search || undefined,
        ...page,
      }),
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
    <CreateListAction resource={ModuleId.tags} href="/console/tags/new">
      {t("tags.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("tags.title")}
      description={t("tags.description")}
      actions={createAction}
      toolbar={
        <ListToolbar query={query} searchPlaceholder={t("tags.search")} />
      }
    >
      <ListTable
        list={list}
        columnCount={3}
        emptyMessage={t("tags.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("tags.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("tags.fields.name")}</Table.Th>
            <Table.Th>{t("tags.fields.description")}</Table.Th>
            <Table.Th>{t("tags.fields.updatedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference
                name={row.name}
                recordKey={row.id}
                href={`/console/tags/${row.id}`}
              />
            </Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed">
                {row.description}
              </Text>
            </Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed">
                {showInstant(row.updated_at)}
              </Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
