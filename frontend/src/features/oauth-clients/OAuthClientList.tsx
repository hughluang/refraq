"use client";

import { Badge, Group, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { StatusBadge } from "@/components/display/StatusBadge";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { listOAuthClients } from "@/features/oauth-clients/api";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function OAuthClientList() {
  const t = useTranslate();
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) =>
      listOAuthClients({ q: query.search || undefined, ...page }),
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
    <CreateListAction
      resource={ModuleId.oauthClients}
      href="/console/oauth-clients/new"
    >
      {t("oauthClients.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("oauthClients.title")}
      description={t("oauthClients.description")}
      actions={createAction}
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("oauthClients.search")}
        />
      }
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("oauthClients.empty")}
        emptyAction={createAction}
        noMatchMessage={t("oauthClients.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("oauthClients.fields.name")}</Table.Th>
            <Table.Th>{t("oauthClients.fields.authMethod")}</Table.Th>
            <Table.Th>{t("oauthClients.fields.surfaces")}</Table.Th>
            <Table.Th>{t("oauthClients.fields.status")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((item) => (
          <Table.Tr key={item.id}>
            <Table.Td>
              <RecordReference
                name={item.name}
                recordKey={item.client_id}
                href={`/console/oauth-clients/${item.id}`}
              />
            </Table.Td>
            <Table.Td>
              <Text ff="monospace" size="xs">
                {item.token_endpoint_auth_method}
              </Text>
            </Table.Td>
            <Table.Td>
              <Group gap={4}>
                {item.allowed_surfaces.map((surface) => (
                  <Badge key={surface} size="xs" variant="light">
                    {surface}
                  </Badge>
                ))}
              </Group>
            </Table.Td>
            <Table.Td>
              <StatusBadge
                tone={item.enabled ? "success" : "neutral"}
                labelKey={item.enabled ? "status.enabled" : "status.disabled"}
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
