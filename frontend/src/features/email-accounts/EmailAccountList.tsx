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
import { listEmailAccounts } from "@/features/email-accounts/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function EmailAccountList() {
  const t = useTranslate();
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) => listEmailAccounts({ q: query.search || undefined, ...page }),
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
    <CreateListAction resource={ModuleId.emailAccounts} href="/console/email-accounts/new">
      {t("emailAccounts.create")}
    </CreateListAction>
  );
  return (
    <PageChrome
      title={t("emailAccounts.title")}
      description={t("emailAccounts.description")}
      actions={createAction}
      toolbar={<ListToolbar query={query} searchPlaceholder={t("emailAccounts.search")} />}
    >
      <ListTable
        list={list}
        columnCount={3}
        emptyMessage={t("emailAccounts.empty")}
        emptyAction={createAction}
        noMatchMessage={t("emailAccounts.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("emailAccounts.fields.name")}</Table.Th>
            <Table.Th>{t("emailAccounts.fields.host")}</Table.Th>
            <Table.Th>{t("emailAccounts.fields.from")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((account) => (
          <Table.Tr key={account.id}>
            <Table.Td>
              <RecordReference
                name={account.name}
                recordKey={account.id}
                href={`/console/email-accounts/${account.id}`}
              />
            </Table.Td>
            <Table.Td>
              {account.host}:{account.port}
            </Table.Td>
            <Table.Td>{account.from}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
