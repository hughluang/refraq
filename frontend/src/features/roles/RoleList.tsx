"use client";

import { Badge, Button, Group, Table, Text } from "@mantine/core";
import {
  CanAccess,
  useCan,
  useDelete,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import Link from "next/link";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { listRoles } from "@/features/roles/api";
import type { RoleRow } from "@/features/roles/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function RoleList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.roles,
    action: ModuleAction.create,
  });
  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback((query: PageQuery) => listRoles(query), []);
  const {
    items: rows,
    total,
    page,
    setPage,
    loading,
    error: errorMessage,
    reload,
    pageSize,
  } = usePagedList<RoleRow>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    onError,
  });
  const { mutate: deleteRole, mutation } = useDelete();
  const deleteConfirm = useConfirmAction<RoleRow>();

  const listPresentation = listPresentationOf({
    loading,
    error: errorMessage,
    total,
    itemCount: rows.length,
    filtered: false,
  });

  function confirmDelete() {
    const pending = deleteConfirm.pending;
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
      {
        onSuccess: () => {
          void reload();
        },
        onSettled: () => deleteConfirm.close(),
      },
    );
  }

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
    >
      <ListTable
        state={listPresentation.state}
        columnCount={5}
        refreshing={listPresentation.refreshing}
        errorMessage={errorMessage}
        onRetry={() => void reload()}
        head={
          <Table.Tr>
            <Table.Th>{t("roles.fields.key")}</Table.Th>
            <Table.Th>{t("roles.fields.name")}</Table.Th>
            <Table.Th>{t("roles.fields.permissions")}</Table.Th>
            <Table.Th>{t("roles.fields.users")}</Table.Th>
            <Table.Th>{t("roles.fields.actions")}</Table.Th>
          </Table.Tr>
        }
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
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
                      onClick={() => deleteConfirm.open(row)}
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

      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("roles.delete.confirmTitle")}
        body={
          deleteConfirm.pending
            ? t("roles.delete.confirmBody", { name: deleteConfirm.pending.name })
            : null
        }
        confirmColor="red"
        loading={mutation.isPending}
        onConfirm={confirmDelete}
      />
    </PageChrome>
  );
}
