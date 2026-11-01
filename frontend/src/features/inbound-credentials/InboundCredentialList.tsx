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
import { listInboundCredentials } from "@/features/inbound-credentials/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function InboundCredentialList() {
  const t = useTranslate();
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) => listInboundCredentials({ q: query.search || undefined, ...page }),
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
    <CreateListAction resource={ModuleId.inboundCredentials} href="/console/inbound-credentials/new">
      {t("inboundCredentials.create")}
    </CreateListAction>
  );
  return (
    <PageChrome
      title={t("inboundCredentials.title")}
      description={t("inboundCredentials.description")}
      actions={createAction}
      toolbar={<ListToolbar query={query} searchPlaceholder={t("inboundCredentials.search")} />}
    >
      <ListTable
        list={list}
        columnCount={2}
        emptyMessage={t("inboundCredentials.empty")}
        emptyAction={createAction}
        noMatchMessage={t("inboundCredentials.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("inboundCredentials.fields.name")}</Table.Th>
            <Table.Th>{t("inboundCredentials.list.type")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((credential) => (
          <Table.Tr key={credential.id}>
            <Table.Td>
              <RecordReference
                name={credential.name}
                recordKey={credential.id}
                href={`/console/inbound-credentials/${credential.id}`}
              />
            </Table.Td>
            <Table.Td>{t(`inboundCredentials.types.${credential.type}`)}</Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
