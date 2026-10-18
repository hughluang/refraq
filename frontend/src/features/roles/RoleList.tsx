"use client";

import { Badge, Group, Table, Text } from "@mantine/core";
import { useCan, useDelete, useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { listRoles } from "@/features/roles/api";
import type { RoleRow } from "@/features/roles/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function RoleList() {
  const t = useTranslate();
  const { push } = useConsoleNavigation();
  const { data: canWrite } = useCan({
    resource: ModuleId.roles,
    action: ModuleAction.edit,
  });
  const { data: canDelete } = useCan({
    resource: ModuleId.roles,
    action: ModuleAction.delete,
  });
  const query = useListQuery();
  const fetchPage = useCallback(
    (page: PageQuery) => listRoles({ ...page, q: query.search || undefined }),
    [query.search],
  );
  const list = useConsolePagedList<RoleRow>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items: rows, reload } = list;
  const { mutate: deleteRole } = useDelete();

  const createAction = (
    <CreateListAction resource={ModuleId.roles} href="/console/roles/new">
      {t("roles.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("roles.title")}
      description={t("roles.description")}
      actions={createAction}
      toolbar={
        <ListToolbar query={query} searchPlaceholder={t("roles.search")} />
      }
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("roles.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("roles.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("roles.fields.name")}</Table.Th>
            <Table.Th>{t("roles.fields.permissions")}</Table.Th>
            <Table.Th>{t("roles.fields.users")}</Table.Th>
            <Table.Th>{t("roles.fields.actions")}</Table.Th>
          </Table.Tr>
        }
      >
        {rows.map((row) => {
          const recordName = row.name;
          const deleteReason = row.locked
            ? t("roles.delete.locked")
            : row.user_count > 0
              ? t("roles.delete.assigned")
              : undefined;
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Group gap="xs">
                  <RecordReference
                    name={row.name}
                    recordKey={row.key}
                    href={`/console/roles/${row.id}`}
                  />
                  {row.locked ? (
                    <Badge size="xs" color="red" variant="light">
                      {t("roles.locked")}
                    </Badge>
                  ) : null}
                </Group>
              </Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {row.permissions.length}
                </Text>
              </Table.Td>
              <Table.Td>{row.user_count}</Table.Td>
              <Table.Td>
                <RowActions
                  recordName={recordName}
                  verbs={[
                    {
                      key: "edit",
                      label: t("roles.edit"),
                      hidden: !canWrite?.can,
                      disabledReason: row.locked ? t("roles.lockedHint") : undefined,
                      safety: "immediate",
                      onClick: () => push(`/console/roles/${row.id}`),
                    },
                    {
                      key: "delete",
                      label: t("roles.delete"),
                      color: "red",
                      hidden: !canDelete?.can,
                      disabledReason: deleteReason,
                      action: {
                        safety: "confirm",
                        recordName,
                        title: t("roles.delete.confirmTitle"),
                        consequence: t("roles.delete.consequence"),
                        confirmLabel: t("roles.delete"),
                        confirmColor: "red",
                        outcome: t("roles.delete.success"),
                        execute: () =>
                          new Promise<void>((resolve, reject) => {
                            deleteRole(
                              {
                                resource: ModuleId.roles,
                                id: row.id,
                                successNotification: false,
                                errorNotification: false,
                              },
                              {
                                onSuccess: () => resolve(),
                                onError: (error) => reject(error),
                              },
                            );
                          }),
                        onSuccess: () => reload(),
                      },
                    },
                  ]}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </PageChrome>
  );
}
