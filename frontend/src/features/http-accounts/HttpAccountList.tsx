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
import { listHttpAccounts } from "@/features/http-accounts/api";
import type { HttpAccount } from "@/features/http-accounts/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function HttpAccountList() {
  const t = useTranslate();
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) => listHttpAccounts({ q: query.search || undefined, ...page }),
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
    <CreateListAction resource={ModuleId.httpAccounts} href="/console/http-accounts/new">
      {t("httpAccounts.create")}
    </CreateListAction>
  );
  return (
    <PageChrome
      title={t("httpAccounts.title")}
      description={t("httpAccounts.description")}
      actions={createAction}
      toolbar={<ListToolbar query={query} searchPlaceholder={t("httpAccounts.search")} />}
    >
      <ListTable
        list={list}
        columnCount={3}
        emptyMessage={t("httpAccounts.empty")}
        emptyAction={createAction}
        noMatchMessage={t("httpAccounts.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("httpAccounts.fields.name")}</Table.Th>
            <Table.Th>{t("httpAccounts.list.auth")}</Table.Th>
            <Table.Th>{t("httpAccounts.list.origins")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((account) => (
          <Table.Tr key={account.id}>
            <Table.Td>
              <RecordReference
                name={account.name}
                recordKey={account.id}
                href={`/console/http-accounts/${account.id}`}
              />
            </Table.Td>
            <Table.Td>{t(`httpAccounts.auth.${account.auth.type}`)}</Table.Td>
            <Table.Td>{originSummary(account, t)}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}

function originSummary(account: HttpAccount, t: (key: string) => string) {
  if (account.allowed_origins.length === 0) return t("httpAccounts.list.anyOrigin");
  return account.allowed_origins.join(", ");
}
