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
  useCan,
  useNotification,
  useTable,
  useTranslate,
} from "@refinedev/core";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { createToken, revokeToken } from "@/features/tokens/api";
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
  revoked: "red",
};

type CreateFormValues = {
  name: string;
  expires_at: string;
};

export function TokenList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.tokens,
    action: ModuleAction.create,
  });
  const { tableQuery, currentPage, pageCount, setCurrentPage } =
    useTable<TokenMetadata>({
      resource: ModuleId.tokens,
      pagination: { mode: "client", pageSize: 20 },
    });

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<TokenMetadata | null>(
    null,
  );
  const [revoking, setRevoking] = useState(false);

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

  async function confirmRevoke() {
    if (!pendingRevoke) return;
    setRevoking(true);
    try {
      await revokeToken(pendingRevoke.id);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.revoke.success"),
      });
      setPendingRevoke(null);
      await tableQuery.refetch();
    } catch (err) {
      open?.({
        type: "error",
        message: t("tokens.title"),
        description:
          err instanceof ApiError ? err.detail : t("tokens.revoke.error"),
      });
    } finally {
      setRevoking(false);
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
      <PageChrome
        title={t("tokens.title")}
        description={t("tokens.description")}
      >
        <PageError message={message} onRetry={() => tableQuery.refetch()} />
      </PageChrome>
    );
  }

  return (
    <PageChrome
      title={t("tokens.title")}
      description={t("tokens.description")}
      actions={createAction}
    >
      {isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState
          action={
            canWrite?.can ? (
              <Button size="xs" onClick={openCreate}>
                {t("tokens.create")}
              </Button>
            ) : undefined
          }
        />
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
              const canRevoke = status !== "revoked";
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
                      <Button
                        size="xs"
                        variant="light"
                        color="red"
                        disabled={!canRevoke || revoking}
                        onClick={() => setPendingRevoke(row)}
                      >
                        {t("tokens.revoke")}
                      </Button>
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
        opened={pendingRevoke !== null}
        onClose={() => setPendingRevoke(null)}
        title={t("tokens.revoke.confirmTitle")}
        centered
      >
        <Text size="sm" mb="md">
          {pendingRevoke
            ? t("tokens.revoke.confirmBody", { name: pendingRevoke.name })
            : null}
        </Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={() => setPendingRevoke(null)}
            disabled={revoking}
          >
            {t("common.cancel")}
          </Button>
          <Button color="red" loading={revoking} onClick={() => void confirmRevoke()}>
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>
    </PageChrome>
  );
}
