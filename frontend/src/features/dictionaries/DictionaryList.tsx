"use client";

import { Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { listDictionaries } from "@/features/dictionaries/api";
import { DictionaryStatusBadge } from "@/features/dictionaries/DictionaryStatusBadge";
import {
  DEFAULT_DICTIONARY_LIST_STATUSES,
  type DictionaryListStatus,
} from "@/features/dictionaries/dictionaryListFilter";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function DictionaryList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const query = useListQuery({
    filters: [
      {
        key: "status",
        type: "multi",
        defaultValue: DEFAULT_DICTIONARY_LIST_STATUSES,
      },
    ],
  });
  const statuses = query.multi("status") as readonly DictionaryListStatus[];

  const fetchPage = useCallback(
    (page: PageQuery) => {
      if (statuses.length === 0) {
        return {
          items: [],
          total: 0,
          limit: page.limit,
          offset: page.offset,
        };
      }
      return listDictionaries({
        q: query.search || undefined,
        status: statuses,
        ...page,
      });
    },
    [query.search, statuses],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, statuses],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });

  const createAction = (
    <CreateListAction
      resource={ModuleId.dictionaries}
      href="/console/dictionaries/new"
    >
      {t("dictionaries.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("dictionaries.title")}
      description={t("dictionaries.description")}
      actions={createAction}
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("dictionaries.search")}
          filters={[
            {
              key: "status",
              label: t("dictionaries.fields.status"),
              options: [
                { value: "available", label: t("dictionaries.status.available") },
                { value: "deprecated", label: t("dictionaries.status.deprecated") },
              ],
            },
          ]}
        />
      }
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("dictionaries.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("dictionaries.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("dictionaries.fields.displayName")}</Table.Th>
            <Table.Th>{t("dictionaries.fields.revision")}</Table.Th>
            <Table.Th>{t("dictionaries.fields.status")}</Table.Th>
            <Table.Th>{t("entities.fields.updatedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference
                name={row.display_name}
                recordKey={row.name}
                href={`/console/dictionaries/${row.id}`}
              />
            </Table.Td>
            <Table.Td>{row.revision}</Table.Td>
            <Table.Td>
              <DictionaryStatusBadge deprecated={row.deprecated_at != null} />
            </Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed">
                {formatInstant(row.updated_at)}
              </Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
