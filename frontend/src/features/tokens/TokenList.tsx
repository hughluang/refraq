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
import { CanAccess, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createToken,
  deactivateToken,
  deleteToken,
  listTokens,
  restoreToken,
} from "@/features/tokens/api";
import {
  datetimeLocalToIso,
  defaultExpiresLocalValue,
  tokenStatus,
} from "@/features/tokens/status";
import type { TokenMetadata, TokenStatus } from "@/features/tokens/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

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
  const formatInstant = useFormatInstant();
  const onListError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback((query: PageQuery) => listTokens(query), []);
  const {
    items: rows,
    total,
    page,
    setPage,
    loading,
    error: errorMessage,
    reload,
    pageSize,
  } = usePagedList<TokenMetadata>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    onError: onListError,
  });

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const deactivateConfirm = useConfirmAction<TokenMetadata>();
  const deleteConfirm = useConfirmAction<TokenMetadata>();
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

  const listPresentation = listPresentationOf({
    loading,
    error: errorMessage,
    total,
    itemCount: rows.length,
    filtered: false,
  });

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
      await reload();
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
    const pending = deactivateConfirm.pending;
    if (!pending) return;
    setActionBusy(true);
    try {
      await deactivateToken(pending.id);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.deactivate.success"),
      });
      deactivateConfirm.close();
      await reload();
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
      await reload();
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
    const pending = deleteConfirm.pending;
    if (!pending) return;
    setActionBusy(true);
    try {
      await deleteToken(pending.id);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.delete.success"),
      });
      deleteConfirm.close();
      await reload();
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
    <CreateListAction
      resource={ModuleId.tokens}
      onClick={openCreate}
    >
      {t("tokens.create")}
    </CreateListAction>
  );

  return (
    <Stack gap="sm">
      <SectionHeader
        title={t("tokens.title")}
        description={t("tokens.description")}
        actions={createAction}
        order={4}
      />

      <ListTable
        state={listPresentation.state}
        columnCount={7}
        refreshing={listPresentation.refreshing}
        errorMessage={errorMessage}
        onRetry={() => void reload()}
        head={
          <Table.Tr>
            <Table.Th>{t("tokens.fields.name")}</Table.Th>
            <Table.Th>{t("tokens.fields.prefix")}</Table.Th>
            <Table.Th>{t("tokens.fields.status")}</Table.Th>
            <Table.Th>{t("tokens.fields.expiresAt")}</Table.Th>
            <Table.Th>{t("tokens.fields.createdAt")}</Table.Th>
            <Table.Th>{t("tokens.fields.lastUsedAt")}</Table.Th>
            <Table.Th>{t("tokens.fields.actions")}</Table.Th>
          </Table.Tr>
        }
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
      >
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
              <Table.Td>{formatInstant(row.expires_at)}</Table.Td>
              <Table.Td>{formatInstant(row.created_at)}</Table.Td>
              <Table.Td>{formatInstant(row.last_used_at)}</Table.Td>
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
                          onClick={() => deleteConfirm.open(row)}
                        >
                          {t("tokens.delete")}
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="xs"
                        variant="light"
                        disabled={actionBusy}
                        onClick={() => deactivateConfirm.open(row)}
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
      </ListTable>

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

      <ConfirmActionModal
        opened={deactivateConfirm.opened}
        onClose={deactivateConfirm.close}
        title={t("tokens.deactivate.confirmTitle")}
        body={
          deactivateConfirm.pending
            ? t("tokens.deactivate.confirmBody", {
                name: deactivateConfirm.pending.name,
              })
            : null
        }
        loading={actionBusy}
        onConfirm={() => void confirmDeactivate()}
      />

      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("tokens.delete.confirmTitle")}
        body={
          deleteConfirm.pending
            ? t("tokens.delete.confirmBody", { name: deleteConfirm.pending.name })
            : null
        }
        confirmColor="red"
        loading={actionBusy}
        onConfirm={() => void confirmDelete()}
      />
    </Stack>
  );
}
