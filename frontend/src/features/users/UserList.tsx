"use client";

import {
  Button,
  Group,
  Modal,
  Switch,
  Table,
} from "@mantine/core";
import {
  CanAccess,
  useCan,
  useGetIdentity,
  useTable,
  useTranslate,
  useUpdate,
} from "@refinedev/core";
import Link from "next/link";
import { useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { UserRoleBadge } from "@/features/users/UserRoleBadge";
import type { UserRow, UserStatus } from "@/features/users/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { CurrentUser } from "@/providers/session-store";

const PAGE_SIZE = 50;

export function UserList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const { data: canWrite } = useCan({
    resource: ModuleId.users,
    action: ModuleAction.create,
  });
  const { tableQuery, currentPage, setCurrentPage } = useTable<UserRow>({
    resource: ModuleId.users,
    pagination: { mode: "server", pageSize: PAGE_SIZE },
  });
  const { mutate: updateStatus, mutation } = useUpdate<UserRow>();
  const [pending, setPending] = useState<UserRow | null>(null);

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

  function confirmToggle() {
    if (!pending) return;
    const next: UserStatus =
      pending.status === "active" ? "disabled" : "active";
    updateStatus(
      {
        resource: ModuleId.users,
        id: pending.id,
        values: { status: next },
        meta: { action: "status" },
        successNotification: {
          message: t("users.title"),
          description: t("users.status.update.success"),
          type: "success",
        },
        errorNotification: (err) => ({
          message: t("users.title"),
          description:
            err instanceof ApiError
              ? err.detail
              : t("users.status.update.error"),
          type: "error",
        }),
      },
      {
        onSettled: () => setPending(null),
      },
    );
  }

  const createAction = (
    <CanAccess resource={ModuleId.users} action={ModuleAction.create}>
      <Button component={Link} href="/console/users/new" size="sm">
        {t("users.create")}
      </Button>
    </CanAccess>
  );

  return (
    <PageChrome
      title={t("users.title")}
      description={t("users.description")}
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
            <Table.Th>{t("users.fields.account")}</Table.Th>
            <Table.Th>{t("users.fields.displayName")}</Table.Th>
            <Table.Th>{t("users.fields.role")}</Table.Th>
            <Table.Th>{t("users.fields.status")}</Table.Th>
            <Table.Th>{t("users.fields.lastLoginAt")}</Table.Th>
          </Table.Tr>
        }
        page={currentPage}
        pageSize={PAGE_SIZE}
        total={total}
        onPageChange={setCurrentPage}
      >
        {rows.map((row) => {
          const isSelf = identity?.id === row.id;
          return (
            <Table.Tr key={row.id}>
              <Table.Td>{row.account}</Table.Td>
              <Table.Td>{row.display_name}</Table.Td>
              <Table.Td>
                <UserRoleBadge
                  roleName={row.role_name}
                  roleKey={row.role_key}
                />
              </Table.Td>
              <Table.Td>
                <Switch
                  checked={row.status === "active"}
                  onChange={() => setPending(row)}
                  disabled={!canWrite?.can || mutation.isPending || isSelf}
                  size="sm"
                  aria-label={
                    row.status === "active"
                      ? t("users.status.active")
                      : t("users.status.disabled")
                  }
                />
              </Table.Td>
              <Table.Td>{formatInstant(row.last_login_at)}</Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>

      <Modal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title={t("users.status.confirmTitle")}
        centered
      >
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={() => setPending(null)}>
            {t("common.cancel")}
          </Button>
          <Button loading={mutation.isPending} onClick={confirmToggle}>
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>
    </PageChrome>
  );
}
