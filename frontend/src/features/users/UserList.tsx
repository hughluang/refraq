"use client";

import {
  Badge,
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

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { UserRoleBadge } from "@/features/users/UserRoleBadge";
import type { UserRow, UserStatus } from "@/features/users/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";
import type { CurrentUser } from "@/providers/session-store";

export function UserList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const { data: canWrite } = useCan({
    resource: ModuleId.users,
    action: ModuleAction.create,
  });
  const { tableQuery, currentPage, pageCount, setCurrentPage } =
    useTable<UserRow>({
      resource: ModuleId.users,
      pagination: { mode: "client", pageSize: 20 },
    });
  const { mutate: updateStatus, mutation } = useUpdate<UserRow>();
  const [pending, setPending] = useState<UserRow | null>(null);

  const rows = tableQuery.data?.data ?? [];
  const isLoading = tableQuery.isLoading;
  const error = tableQuery.error;

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

  if (error) {
    const message =
      error instanceof ApiError
        ? error.detail
        : t("common.error.loadFailed");
    return (
      <PageChrome
        title={t("users.title")}
        description={t("users.description")}
      >
        <PageError message={message} onRetry={() => tableQuery.refetch()} />
      </PageChrome>
    );
  }

  return (
    <PageChrome
      title={t("users.title")}
      description={t("users.description")}
      actions={createAction}
    >
      {isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState
          action={
            canWrite?.can ? (
              <Button component={Link} href="/console/users/new" size="xs">
                {t("users.create")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Table highlightOnHover striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("users.fields.account")}</Table.Th>
              <Table.Th>{t("users.fields.displayName")}</Table.Th>
              <Table.Th>{t("users.fields.role")}</Table.Th>
              <Table.Th>{t("users.fields.status")}</Table.Th>
              <Table.Th>{t("users.fields.lastLoginAt")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
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
                    <Group gap="xs">
                      <Switch
                        checked={row.status === "active"}
                        onChange={() => setPending(row)}
                        disabled={
                          !canWrite?.can || mutation.isPending || isSelf
                        }
                        size="sm"
                        aria-label={t("users.fields.status")}
                      />
                      <Badge
                        color={row.status === "active" ? "green" : "gray"}
                        variant="dot"
                      >
                        {row.status === "active"
                          ? t("users.status.active")
                          : t("users.status.disabled")}
                      </Badge>
                    </Group>
                  </Table.Td>
                  <Table.Td>{formatInstant(row.last_login_at)}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      )}

      {pageCount > 1 ? (
        <Group justify="flex-end" mt="md">
          <Button
            size="xs"
            variant="default"
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage(currentPage - 1)}
          >
            {t("common.prev")}
          </Button>
          <Button
            size="xs"
            variant="default"
            disabled={currentPage >= pageCount}
            onClick={() => setCurrentPage(currentPage + 1)}
          >
            {t("common.next")}
          </Button>
        </Group>
      ) : null}

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
