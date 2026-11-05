"use client";

import { Stack, Switch, Table, TextInput } from "@mantine/core";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { FormDialog } from "@/components/form/FormDialog";
import { FieldChrome } from "@/components/form/FieldChrome";
import { collectNotes } from "@/components/form/fieldNotes";
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
  never_expires: boolean;
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
  const [secret, setSecret] = useState<string | null>(null);

  const form = useConsoleForm<CreateFormValues>({
    initialValues: {
      name: "",
      never_expires: false,
      expires_at: defaultExpiresWall(zone),
    },
    validate: {
      name: (value) =>
        value.trim().length > 0 ? null : t("tokens.validation.required"),
      expires_at: (value, values) => {
        if (values.never_expires) return null;
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
      never_expires: false,
      expires_at: defaultExpiresWall(zone),
    });
    form.markSaved();
    form.clearErrors();
    setCreateOpen(true);
  }

  function closeCreate() {
    setCreateOpen(false);
    form.reset();
  }

  async function onCreate(values: CreateFormValues) {
    const expiresAt = values.never_expires ? null : wallToInstant(values.expires_at, zone);
    try {
      const result = await createToken({
        name: values.name.trim(),
        expires_at: expiresAt,
      });
      form.markSaved();
      setCreateOpen(false);
      setSecret(result.secret);
      open?.({
        type: "success",
        message: t("tokens.title"),
        description: t("tokens.create.success"),
      });
      await reload();
    } catch (err) {
      presentSaveFailure(t, err, form.applyApiError);
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
              <Table.Td>
                {row.expires_at == null
                  ? t("tokens.fields.neverExpires")
                  : showInstant(row.expires_at)}
              </Table.Td>
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
          <FieldChrome
            label={t("tokens.fields.expiresAt")}
            description={
              form.values.never_expires
                ? t("tokens.fields.expiresAt.neverHint")
                : t("tokens.fields.expiresAt.hint", { zone })
            }
            required={!form.values.never_expires}
            notes={collectNotes(form.errors.expires_at, undefined)}
            editSignal={form.values.expires_at}
          >
            {({ id, invalid }) => (
              <Stack gap="xs">
                <Switch
                  id={form.values.never_expires ? id : undefined}
                  label={t("tokens.fields.neverExpires")}
                  checked={form.values.never_expires}
                  onChange={(event) => {
                    const on = event.currentTarget.checked;
                    form.setFieldValue("never_expires", on);
                    if (on) form.clearFieldError("expires_at");
                  }}
                />
                {form.values.never_expires ? null : (
                  <TextInput
                    {...form.fieldProps("expires_at")}
                    id={id}
                    type="datetime-local"
                    error={invalid || undefined}
                  />
                )}
              </Stack>
            )}
          </FieldChrome>
        </Stack>
      </FormDialog>

      <SecretRevealDialog secret={secret} onClose={() => setSecret(null)} />
    </Stack>
  );
}
