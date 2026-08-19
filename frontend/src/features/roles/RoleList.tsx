"use client";

import { Badge, Button, Group, Modal, Table, Text } from "@mantine/core";
import {
  CanAccess,
  useCan,
  useDelete,
  useTable,
  useTranslate,
} from "@refinedev/core";
import Link from "next/link";
import { useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import type { RoleRow } from "@/features/roles/types";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";

const PAGE_SIZE = 50;

export function RoleList() {
  const t = useTranslate();
  const { data: canWrite } = useCan({
    resource: ModuleId.roles,
    action: ModuleAction.create,
  });
  const { tableQuery, currentPage, setCurrentPage } = useTable<RoleRow>({
    resource: ModuleId.roles,
    pagination: { mode: "server", pageSize: PAGE_SIZE },
  });
  const { mutate: deleteRole, mutation } = useDelete();
  const [pending, setPending] = useState<RoleRow | null>(null);

  const rows = tableQuery.data?.data ?? [];
  const total = tableQuery.data?.total ?? 0;
  const errorMessage =
    tableQuery.error == null
      ? null
      : tableQuery.error instanceof ApiError
        ? tableQuery.error.detail
        : t("common.error.loadFailed");
  const listPresentation = listPresentationOf({
    loading: tableQuery.isFetching,
    error: errorMessage,
    total,
    itemCount: rows.length,
    filtered: false,
  });

  function confirmDelete() {
    if (!pending) return;
    deleteRole(
      {
        resource: ModuleId.roles,
        id: pending.id,
        successNotification: {
          message: t("roles.title"),
          description: t("roles.delete.success"),
          type: "success",
        },
        errorNotification: (err) => ({
          message: t("roles.title"),
          description:
            err instanceof ApiError
              ? err.detail
              : t("roles.delete.error"),
          type: "error",
        }),
      },
      { onSettled: () => setPending(null) },
    );
  }

  const createAction = (
    <CanAccess resource={ModuleId.roles} action={ModuleAction.create}>
      <Button component={Link} href="/console/roles/new" size="sm">
        {t("roles.create")}
      </Button>
    </CanAccess>
  );

  return (
    <PageChrome
      title={t("roles.title")}
      description={t("roles.description")}
      actions={createAction}
    >
      <ListTable
        state={listPresentation.state}
        columnCount={5}
        refreshing={listPresentation.refreshing}
        errorMessage={errorMessage}
        onRetry={() => void tableQuery.refetch()}
        head={
          <Table.Tr>
            <Table.Th>{t("roles.fields.key")}</Table.Th>
            <Table.Th>{t("roles.fields.name")}</Table.Th>
            <Table.Th>{t("roles.fields.permissions")}</Table.Th>
            <Table.Th>{t("roles.fields.users")}</Table.Th>
            <Table.Th>{t("roles.fields.actions")}</Table.Th>
          </Table.Tr>
        }
        page={currentPage}
        pageSize={PAGE_SIZE}
        total={total}
        onPageChange={setCurrentPage}
      >
        {rows.map((row) => {
          const canDelete =
            canWrite?.can && !row.locked && row.user_count === 0;
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Group gap="xs">
                  <Text size="sm">{row.key}</Text>
                  {row.locked ? (
                    <Badge size="xs" color="red" variant="light">
                      {t("roles.locked")}
                    </Badge>
                  ) : null}
                </Group>
              </Table.Td>
              <Table.Td>{row.name}</Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {row.permissions.length}
                </Text>
              </Table.Td>
              <Table.Td>{row.user_count}</Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <CanAccess
                    resource={ModuleId.roles}
                    action={ModuleAction.edit}
                  >
                    <Button
                      component={Link}
                      href={`/console/roles/${row.id}`}
                      size="xs"
                      variant="light"
                      disabled={row.locked}
                    >
                      {t("roles.edit")}
                    </Button>
                  </CanAccess>
                  <CanAccess
                    resource={ModuleId.roles}
                    action={ModuleAction.delete}
                  >
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      disabled={!canDelete || mutation.isPending}
                      onClick={() => setPending(row)}
                    >
                      {t("roles.delete")}
                    </Button>
                  </CanAccess>
                </Group>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>

      <Modal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title={t("roles.delete.confirmTitle")}
        centered
      >
        <Text size="sm" mb="md">
          {pending
            ? t("roles.delete.confirmBody", { name: pending.name })
            : null}
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setPending(null)}>
            {t("common.cancel")}
          </Button>
          <Button
            color="red"
            loading={mutation.isPending}
            onClick={confirmDelete}
          >
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>
    </PageChrome>
  );
}
