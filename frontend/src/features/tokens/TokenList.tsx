"use client";

import {
  Badge,
  Button,
  Code,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  CanAccess,
  useNotification,
  useTable,
  useTranslate,
} from "@refinedev/core";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createToken,
  deactivateToken,
  deleteToken,
  restoreToken,
} from "@/features/tokens/api";
import {
  datetimeLocalToIso,
  defaultExpiresLocalValue,
  formatTokenInstant,
  tokenStatus,
} from "@/features/tokens/status";
import type { TokenMetadata, TokenStatus } from "@/features/tokens/types";
import { ApiError } from "@/lib/api";

const STATUS_COLOR: Record<TokenStatus, string> = {
  active: "green",
  expired: "gray",
  deactivated: "yellow",
};

type CreateFormValues = {
  name: string;
  expires_at: string;
};

/** User PAT section for Account Center. */
export function TokenList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { tableQuery, currentPage, pageCount, setCurrentPage } =
    useTable<TokenMetadata>({
      resource: ModuleId.tokens,
      pagination: { mode: "client", pageSize: 20 },
    });

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [pendingDeactivate, setPendingDeactivate] =
    useState<TokenMetadata | null>(null);
  const [pendingDelete, setPendingDelete] = useState<TokenMetadata | null>(
    null,
  );
  const [actionBusy, setActionBusy] = useState(false);

  const form = useForm<CreateFormValues>({
    initialValues: {
      name: "",
      expires_at: defaultExpiresLocalValue(),
    },
    validate: {
      name: (value) =>
        value.trim().length > 0 ? null : t("tokens.validation.required"),
      expires_at: (value) => {
        if (!value) {
          return t("tokens.validation.required");
        }
        const expires = new Date(value);
        if (Number.isNaN(expires.getTime()) || expires.getTime() <= Date.now()) {
          return t("tokens.validation.expiresFuture");
        }
        return null;
      },
    },
  });

  const rows = tableQuery.data?.data ?? [];
  const isLoading = tableQuery.isLoading;
  const error = tableQuery.error;

  function openCreate() {
    form.setValues({
      name: "",
      expires_at: defaultExpiresLocalValue(),
    });
    form.clearErrors();
    setCreateOpen(true);
  }

  async function onCreate(values: CreateFormValues) {
    setCreating(true);
    try {
      const result = await createToken({
        name: values.name.trim(),
        expires_at: datetimeLocalToIso(values.expires_at),
      });
      setCreateOpen(false);
      setSecret(result.secret);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.create.success"),
      });
      await tableQuery.refetch();
    } catch (err) {
      open?.({
        type: "error",
        message: t("tokens.title"),
        description:
          err instanceof ApiError ? err.detail : t("tokens.create.error"),
      });
    } finally {
      setCreating(false);
    }
  }

  async function confirmDeactivate() {
    if (!pendingDeactivate) return;
    setActionBusy(true);
    try {
      await deactivateToken(pendingDeactivate.id);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.deactivate.success"),
      });
      setPendingDeactivate(null);
      await tableQuery.refetch();
    } catch (err) {
      open?.({
        type: "error",
        message: t("tokens.title"),
        description:
          err instanceof ApiError ? err.detail : t("tokens.deactivate.error"),
      });
    } finally {
      setActionBusy(false);
    }
  }

  async function onRestore(row: TokenMetadata) {
    setActionBusy(true);
    try {
      await restoreToken(row.id);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.restore.success"),
      });
      await tableQuery.refetch();
    } catch (err) {
      open?.({
        type: "error",
        message: t("tokens.title"),
        description:
          err instanceof ApiError ? err.detail : t("tokens.restore.error"),
      });
    } finally {
      setActionBusy(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setActionBusy(true);
    try {
      await deleteToken(pendingDelete.id);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.delete.success"),
      });
      setPendingDelete(null);
      await tableQuery.refetch();
    } catch (err) {
      open?.({
        type: "error",
        message: t("tokens.title"),
        description:
          err instanceof ApiError ? err.detail : t("tokens.delete.error"),
      });
    } finally {
      setActionBusy(false);
    }
  }

  async function copySecret() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.secret.copied"),
      });
    } catch {
      open?.({
        type: "error",
        message: t("tokens.title"),
        description: t("tokens.secret.copyFailed"),
      });
    }
  }

  const createAction = (
    <CanAccess resource={ModuleId.tokens} action={ModuleAction.create}>
      <Button size="sm" onClick={openCreate}>
        {t("tokens.create")}
      </Button>
    </CanAccess>
  );

  if (error) {
    const message =
      error instanceof ApiError
        ? error.detail
        : t("common.error.loadFailed");
    return (
      <Stack gap="sm">
        <SectionHeader
          title={t("tokens.title")}
          description={t("tokens.description")}
          order={4}
        />
        <PageError message={message} onRetry={() => tableQuery.refetch()} />
      </Stack>
    );
  }

  return (
    <Stack gap="sm">
      <SectionHeader
        title={t("tokens.title")}
        description={t("tokens.description")}
        actions={createAction}
        order={4}
      />

      {isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <Table highlightOnHover striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("tokens.fields.name")}</Table.Th>
              <Table.Th>{t("tokens.fields.prefix")}</Table.Th>
              <Table.Th>{t("tokens.fields.status")}</Table.Th>
              <Table.Th>{t("tokens.fields.expiresAt")}</Table.Th>
              <Table.Th>{t("tokens.fields.createdAt")}</Table.Th>
              <Table.Th>{t("tokens.fields.lastUsedAt")}</Table.Th>
              <Table.Th>{t("tokens.fields.actions")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => {
              const status = tokenStatus(row);
              const isDeactivated = status === "deactivated";
              return (
                <Table.Tr key={row.id}>
                  <Table.Td>{row.name}</Table.Td>
                  <Table.Td>
                    <Code>{row.prefix}</Code>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      size="xs"
                      color={STATUS_COLOR[status]}
                      variant="light"
                    >
                      {t(`tokens.status.${status}`)}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{formatTokenInstant(row.expires_at)}</Table.Td>
                  <Table.Td>{formatTokenInstant(row.created_at)}</Table.Td>
                  <Table.Td>{formatTokenInstant(row.last_used_at)}</Table.Td>
                  <Table.Td>
                    <CanAccess
                      resource={ModuleId.tokens}
                      action={ModuleAction.delete}
                    >
                      <Group gap="xs" wrap="nowrap">
                        {isDeactivated ? (
                          <>
                            <Button
                              size="xs"
                              variant="light"
                              disabled={actionBusy}
                              onClick={() => void onRestore(row)}
                            >
                              {t("tokens.restore")}
                            </Button>
                            <Button
                              size="xs"
                              variant="light"
                              color="red"
                              disabled={actionBusy}
                              onClick={() => setPendingDelete(row)}
                            >
                              {t("tokens.delete")}
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="xs"
                            variant="light"
                            disabled={actionBusy}
                            onClick={() => setPendingDeactivate(row)}
                          >
                            {t("tokens.deactivate")}
                          </Button>
                        )}
                      </Group>
                    </CanAccess>
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
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t("tokens.create.title")}
        centered
      >
        <form onSubmit={form.onSubmit(onCreate)}>
          <Stack gap="md">
            <TextInput
              label={t("tokens.fields.name")}
              placeholder={t("tokens.fields.name.placeholder")}
              withAsterisk
              {...form.getInputProps("name")}
            />
            <TextInput
              type="datetime-local"
              label={t("tokens.fields.expiresAt")}
              description={t("tokens.fields.expiresAt.hint")}
              withAsterisk
              {...form.getInputProps("expires_at")}
            />
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setCreateOpen(false)}
                disabled={creating}
              >
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={creating}>
                {t("tokens.create.submit")}
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>

      <Modal
        opened={secret !== null}
        onClose={() => setSecret(null)}
        title={t("tokens.secret.title")}
        centered
        closeOnClickOutside={false}
      >
        <Stack gap="md">
          <Text size="sm">{t("tokens.secret.warning")}</Text>
          <Code block style={{ wordBreak: "break-all" }}>
            {secret}
          </Code>
          <Group justify="flex-end">
            <Button variant="light" onClick={() => void copySecret()}>
              {t("tokens.secret.copy")}
            </Button>
            <Button onClick={() => setSecret(null)}>
              {t("tokens.secret.done")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={pendingDeactivate !== null}
        onClose={() => setPendingDeactivate(null)}
        title={t("tokens.deactivate.confirmTitle")}
        centered
      >
        <Text size="sm" mb="md">
          {pendingDeactivate
            ? t("tokens.deactivate.confirmBody", {
                name: pendingDeactivate.name,
              })
            : null}
        </Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={() => setPendingDeactivate(null)}
            disabled={actionBusy}
          >
            {t("common.cancel")}
          </Button>
          <Button
            loading={actionBusy}
            onClick={() => void confirmDeactivate()}
          >
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>

      <Modal
        opened={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title={t("tokens.delete.confirmTitle")}
        centered
      >
        <Text size="sm" mb="md">
          {pendingDelete
            ? t("tokens.delete.confirmBody", { name: pendingDelete.name })
            : null}
        </Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={() => setPendingDelete(null)}
            disabled={actionBusy}
          >
            {t("common.cancel")}
          </Button>
          <Button
            color="red"
            loading={actionBusy}
            onClick={() => void confirmDelete()}
          >
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>
    </Stack>
  );
}
