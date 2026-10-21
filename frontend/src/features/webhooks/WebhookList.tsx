"use client";

import { Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { listWebhooks } from "@/features/webhooks/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function WebhookList() {
  const t = useTranslate();
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) => listWebhooks({ q: query.search || undefined, ...page }),
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
    <CreateListAction resource={ModuleId.webhooks} href="/console/webhooks/new">
      {t("webhooks.create")}
    </CreateListAction>
  );
  return (
    <PageChrome
      title={t("webhooks.title")}
      description={t("webhooks.description")}
      actions={createAction}
      toolbar={<ListToolbar query={query} searchPlaceholder={t("webhooks.search")} />}
    >
      <ListTable
        list={list}
        columnCount={2}
        emptyMessage={t("webhooks.empty")}
        emptyAction={createAction}
        noMatchMessage={t("webhooks.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("webhooks.fields.name")}</Table.Th>
            <Table.Th>{t("webhooks.fields.url")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((webhook) => (
          <Table.Tr key={webhook.id}>
            <Table.Td>
              <RecordReference
                name={webhook.name}
                recordKey={webhook.id}
                href={`/console/webhooks/${webhook.id}`}
              />
            </Table.Td>
            <Table.Td>{webhook.url}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
