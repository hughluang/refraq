"use client";

import { Stack, Table } from "@mantine/core";
import { FormDialog } from "@/components/form/FormDialog";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentTokenStatus } from "@/components/display/statusTone";
import { TextField } from "@/components/form/TextField";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createToken,
  deactivateToken,
  deleteToken,
  listTokens,
  restoreToken,
} from "@/features/tokens/api";
import { defaultExpiresWall, tokenStatus } from "@/features/tokens/status";
import type { TokenMetadata } from "@/features/tokens/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { useEntryZone, useShowInstant } from "@/hooks/useFormatInstant";
import { SecretRevealDialog } from "@/features/tokens/SecretRevealDialog";
import type { PageQuery } from "@/lib/pagination";
import { wallToInstant } from "@/lib/wall-time";

const PAGE_SIZE = 50;

type CreateFormValues = {
  name: string;
  expires_at: string;
};

/** User PAT section for Account Center. */
export function TokenList() {
  const t = useTranslate();
  const { open } = useNotification();
  const showInstant = useShowInstant();
  const zone = useEntryZone();
  const { data: canDelete } = useCan({
    resource: ModuleId.tokens,
    action: ModuleAction.delete,
  });
  const query = useListQuery({ search: false });
  const fetchPage = useCallback((page: PageQuery) => listTokens(page), []);
  const list = useConsolePagedList<TokenMetadata>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items: rows, reload } = list;

  const [createOpen, setCreateOpen] = useState(false);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  const form = useConsoleForm<CreateFormValues>({
    initialValues: {
      name: "",
      expires_at: defaultExpiresWall(zone),
    },
    onValuesChange: () => setSaveFailure(null),
    validate: {
      name: (value) =>
        value.trim().length > 0 ? null : t("tokens.validation.required"),
      expires_at: (value) => {
        const expires = value ? wallToInstant(value, zone) : null;
        if (!expires) {
          return t("tokens.validation.required");
        }
        if (Date.parse(expires) <= Date.now()) {
          return t("tokens.validation.expiresFuture");
        }
        return null;
      },
    },
  });

  function openCreate() {
    form.setValues({
      name: "",
      expires_at: defaultExpiresWall(zone),
    });
    form.markSaved();
    form.clearErrors();
    setSaveFailure(null);
    setCreateOpen(true);
  }

  function closeCreate() {
    setCreateOpen(false);
    setSaveFailure(null);
    form.reset();
  }

  async function onCreate(values: CreateFormValues) {
    const expiresAt = wallToInstant(values.expires_at, zone);
    if (!expiresAt) return;
    try {
      const result = await createToken({
        name: values.name.trim(),
        expires_at: expiresAt,
      });
      form.markSaved();
      setSaveFailure(null);
      setCreateOpen(false);
      setSecret(result.secret);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.create.success"),
      });
      await reload();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(t, err, form.applyApiError(err), t("tokens.create.error")),
      );
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
        list={list}
        columnCount={6}
        emptyMessage={t("tokens.list.empty")}
        emptyAction={createAction}
        head={
          <Table.Tr>
            <Table.Th>{t("tokens.fields.name")}</Table.Th>
            <Table.Th>{t("tokens.fields.status")}</Table.Th>
            <Table.Th>{t("tokens.fields.expiresAt")}</Table.Th>
            <Table.Th>{t("tokens.fields.createdAt")}</Table.Th>
            <Table.Th>{t("tokens.fields.lastUsedAt")}</Table.Th>
            <Table.Th>{t("tokens.fields.actions")}</Table.Th>
          </Table.Tr>
        }
      >
        {rows.map((row) => {
          const status = tokenStatus(row);
          const statusTone = presentTokenStatus(status);
          const isDeactivated = status === "deactivated";
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <RecordReference name={row.name} recordKey={row.prefix} />
              </Table.Td>
              <Table.Td>
                <StatusBadge
                  size="xs"
                  tone={statusTone.tone}
                  labelKey={statusTone.labelKey}
                />
              </Table.Td>
              <Table.Td>{showInstant(row.expires_at)}</Table.Td>
              <Table.Td>{showInstant(row.created_at)}</Table.Td>
              <Table.Td>{showInstant(row.last_used_at)}</Table.Td>
              <Table.Td>
                <RowActions
                  recordName={row.name}
                  verbs={
                    isDeactivated
                      ? [
                          {
                            key: "restore",
                            label: t("tokens.restore"),
                            hidden: !canDelete?.can,
                            action: {
                              safety: "undoable" as const,
                              recordName: row.name,
                              outcome: t("tokens.restore.outcome"),
                              execute: () => restoreToken(row.id),
                              undo: () => deactivateToken(row.id),
                              onSuccess: () => reload(),
                            },
                          },
                          {
                            key: "delete",
                            label: t("tokens.delete"),
                            color: "red",
                            hidden: !canDelete?.can,
                            action: {
                              safety: "confirm" as const,
                              recordName: row.name,
                              title: t("tokens.delete.confirmTitle"),
                              consequence: t("tokens.delete.consequence"),
                              confirmLabel: t("tokens.delete"),
                              confirmColor: "red",
                              outcome: t("tokens.delete.success"),
                              execute: () => deleteToken(row.id),
                              onSuccess: () => reload(),
                            },
                          },
                          {
                            key: "deactivate",
                            label: t("tokens.deactivate"),
                            hidden: !canDelete?.can,
                            disabledReason: t("tokens.deactivate.unavailable"),
                            action: {
                              safety: "confirm" as const,
                              recordName: row.name,
                              title: t("tokens.deactivate.confirmTitle"),
                              consequence: t("tokens.deactivate.consequence"),
                              confirmLabel: t("tokens.deactivate"),
                              confirmColor: "red",
                              outcome: t("tokens.deactivate.success"),
                              execute: () => deactivateToken(row.id),
                              onSuccess: () => reload(),
                            },
                          },
                        ]
                      : [
                          {
                            key: "deactivate",
                            label: t("tokens.deactivate"),
                            hidden: !canDelete?.can,
                            action: {
                              safety: "confirm" as const,
                              recordName: row.name,
                              title: t("tokens.deactivate.confirmTitle"),
                              consequence: t("tokens.deactivate.consequence"),
                              confirmLabel: t("tokens.deactivate"),
                              confirmColor: "red",
                              outcome: t("tokens.deactivate.success"),
                              execute: () => deactivateToken(row.id),
                              onSuccess: () => reload(),
                            },
                          },
                          {
                            key: "restore",
                            label: t("tokens.restore"),
                            hidden: !canDelete?.can,
                            disabledReason: t("tokens.restore.unavailable"),
                            action: {
                              safety: "undoable" as const,
                              recordName: row.name,
                              outcome: t("tokens.restore.outcome"),
                              execute: () => restoreToken(row.id),
                              undo: () => deactivateToken(row.id),
                              onSuccess: () => reload(),
                            },
                          },
                          {
                            key: "delete",
                            label: t("tokens.delete"),
                            color: "red",
                            hidden: !canDelete?.can,
                            disabledReason: t("tokens.delete.unavailable"),
                            action: {
                              safety: "confirm" as const,
                              recordName: row.name,
                              title: t("tokens.delete.confirmTitle"),
                              consequence: t("tokens.delete.consequence"),
                              confirmLabel: t("tokens.delete"),
                              confirmColor: "red",
                              outcome: t("tokens.delete.success"),
                              execute: () => deleteToken(row.id),
                              onSuccess: () => reload(),
                            },
                          },
                        ]
                  }
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>

      <FormDialog
        opened={createOpen}
        onClose={closeCreate}
        title={t("tokens.create.title")}
        dirty={form.dirty}
        submitting={form.submitting}
        submitLabel={t("tokens.create.submit")}
        summary={<FormErrorSummary failure={saveFailure} />}
        onSubmit={() => void form.submit(onCreate)}
      >
        <Stack gap="md">
          <TextField
            editable
            label={t("tokens.fields.name")}
            placeholder={t("tokens.fields.name.placeholder")}
            withAsterisk
            {...form.fieldProps("name")}
          />
          <TextField
            editable
            type="datetime-local"
            label={t("tokens.fields.expiresAt")}
            description={t("tokens.fields.expiresAt.hint", { zone })}
            withAsterisk
            {...form.fieldProps("expires_at")}
          />
        </Stack>
      </FormDialog>

      <SecretRevealDialog secret={secret} onClose={() => setSecret(null)} />
    </Stack>
  );
}
