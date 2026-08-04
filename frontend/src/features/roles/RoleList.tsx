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

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import type { RoleRow } from "@/features/roles/types";
import { ApiError } from "@/lib/api";

export function RoleList() {
  const t = useTranslate();
  const { data: canWrite } = useCan({ resource: "roles", action: "create" });
  const { tableQuery, currentPage, pageCount, setCurrentPage } =
    useTable<RoleRow>({
      resource: "roles",
      pagination: { mode: "client", pageSize: 20 },
    });
  const { mutate: deleteRole, mutation } = useDelete();
  const [pending, setPending] = useState<RoleRow | null>(null);

  const rows = tableQuery.data?.data ?? [];
  const isLoading = tableQuery.isLoading;
  const error = tableQuery.error;

  function confirmDelete() {
    if (!pending) return;
    deleteRole(
      {
        resource: "roles",
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
    <CanAccess resource="roles" action="create">
      <Button component={Link} href="/console/roles/new" size="sm">
        {t("roles.create")}
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
        title={t("roles.title")}
        description={t("roles.description")}
      >
        <PageError message={message} onRetry={() => tableQuery.refetch()} />
      </PageChrome>
    );
  }

  return (
    <PageChrome
      title={t("roles.title")}
      description={t("roles.description")}
      actions={createAction}
    >
      {isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState
          action={
            canWrite?.can ? (
              <Button component={Link} href="/console/roles/new" size="xs">
                {t("roles.create")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Table highlightOnHover striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("roles.fields.key")}</Table.Th>
              <Table.Th>{t("roles.fields.name")}</Table.Th>
              <Table.Th>{t("roles.fields.permissions")}</Table.Th>
              <Table.Th>{t("roles.fields.users")}</Table.Th>
              <Table.Th>{t("roles.fields.actions")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
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
                      <CanAccess resource="roles" action="edit">
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
                      <CanAccess resource="roles" action="delete">
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
