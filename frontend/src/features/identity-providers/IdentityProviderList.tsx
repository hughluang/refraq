"use client";

import { Checkbox, Code, Modal, Stack, Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentIdentityProviderEnabled } from "@/components/display/statusTone";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions, type RowActionVerb } from "@/components/display/RowActions";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createIdentityProvider,
  deleteIdentityProvider,
  getIdentityProvider,
  listIdentityProviders,
  patchIdentityProvider,
  testIdentityProvider,
} from "@/features/identity-providers/api";
import {
  SpecDrivenForm,
  providerPayload,
} from "@/features/identity-providers/SpecDrivenForm";
import type {
  IdentityProvider,
  IdentityProviderFormValues,
  IdentityProviderTestResult,
} from "@/features/identity-providers/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function IdentityProviderList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canEdit } = useCan({
    resource: ModuleId.identityProviders,
    action: ModuleAction.edit,
  });
  const { data: canDelete } = useCan({
    resource: ModuleId.identityProviders,
    action: ModuleAction.delete,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<IdentityProvider | undefined>();
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] =
    useState<IdentityProviderTestResult | null>(null);
  const deleteConfirm = useConfirmAction<IdentityProvider>();
  const disableConfirm = useConfirmAction<IdentityProvider>();
  const [disableBoundUsers, setDisableBoundUsers] = useState(false);
  const [cascadeOnDisable, setCascadeOnDisable] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [disabling, setDisabling] = useState(false);

  const query = useListQuery({ search: false });
  const fetchPage = useCallback(
    (page: PageQuery) => listIdentityProviders(page),
    [],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;
  const showActions = Boolean(canEdit?.can || canDelete?.can);

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: problemMessage(t, err, fallback),
    });
  };

  const save = async (values: IdentityProviderFormValues) => {
    const payload = providerPayload(values, editing ? "edit" : "create");
    if (editing) {
      await patchIdentityProvider(editing.id, payload);
      open?.({
        type: "success",
        message: t("identityProviders.update.success"),
      });
    } else {
      await createIdentityProvider(payload);
      open?.({
        type: "success",
        message: t("identityProviders.create.success"),
      });
    }
    setFormOpen(false);
    setEditing(undefined);
    await reload();
  };

  const toggleEnabled = async (row: IdentityProvider) => {
    if (row.enabled) {
      disableConfirm.open(row);
      setCascadeOnDisable(false);
      try {
        const { provider } = await getIdentityProvider(row.id);
        disableConfirm.open(provider);
      } catch (err) {
        notifyError(err, t("common.error.loadFailed"));
      }
    }
  };

  const confirmDisable = async () => {
    const pending = disableConfirm.pending;
    if (!pending) return;
    setDisabling(true);
    try {
      await patchIdentityProvider(
        pending.id,
        { enabled: false },
        { disableBoundUsers: cascadeOnDisable },
      );
      open?.({
        type: "success",
        message: t("identityProviders.disable.success"),
      });
      disableConfirm.close();
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setDisabling(false);
    }
  };

  const runTest = async (row: IdentityProvider) => {
    setTestingId(row.id);
    try {
      const result = await testIdentityProvider(row.id);
      setTestResult(result);
    } catch (err) {
      notifyError(err, t("identityProviders.test.failed"));
    } finally {
      setTestingId(null);
    }
  };

  const openDelete = async (row: IdentityProvider) => {
    deleteConfirm.open(row);
    setDisableBoundUsers(false);
    try {
      const { provider } = await getIdentityProvider(row.id);
      deleteConfirm.open(provider);
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    }
  };

  const confirmDelete = async () => {
    const pending = deleteConfirm.pending;
    if (!pending) return;
    setDeleting(true);
    try {
      await deleteIdentityProvider(pending.id, disableBoundUsers);
      open?.({
        type: "success",
        message: t("identityProviders.delete.success"),
      });
      deleteConfirm.close();
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setDeleting(false);
    }
  };

  const createAction = (
    <CreateListAction
      resource={ModuleId.identityProviders}
      onClick={() => {
        setEditing(undefined);
        setFormOpen(true);
      }}
    >
      {t("identityProviders.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("identityProviders.title")}
      description={t("identityProviders.description")}
      actions={createAction}
    >
      <ListTable
        list={list}
        columnCount={showActions ? 8 : 7}
        emptyMessage={t("identityProviders.empty")}
        emptyAction={createAction}
        head={
          <Table.Tr>
            <Table.Th>{t("identityProviders.fields.display_name")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.protocol")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.issuer")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.group_claim")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.status")}</Table.Th>
            <Table.Th>
              {t("identityProviders.fields.client_secret_configured")}
            </Table.Th>
            <Table.Th>{t("identityProviders.fields.boundUsers")}</Table.Th>
            {showActions ? (
              <Table.Th>{t("identityProviders.fields.actions")}</Table.Th>
            ) : null}
          </Table.Tr>
        }
      >
        {items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference name={row.display_name} recordKey={row.client_id} />
            </Table.Td>
            <Table.Td>{row.protocol}</Table.Td>
            <Table.Td>
              <Text size="sm" lineClamp={1}>
                {row.issuer}
              </Text>
            </Table.Td>
            <Table.Td>
              {row.group_claim || t("identityProviders.fields.notConfigured")}
            </Table.Td>
            <Table.Td>
              <StatusBadge
                tone={presentIdentityProviderEnabled(row.enabled).tone}
                labelKey={presentIdentityProviderEnabled(row.enabled).labelKey}
              />
            </Table.Td>
            <Table.Td>
              {row.client_secret_configured
                ? t("identityProviders.status.enabled")
                : t("identityProviders.fields.notConfigured")}
            </Table.Td>
            <Table.Td>{row.bound_user_count}</Table.Td>
            {showActions ? (
              <Table.Td>
                <RowActions
                  recordName={row.display_name}
                  verbs={[
                    {
                      key: "edit",
                      label: t("actions.edit"),
                      hidden: !canEdit?.can,
                      safety: "immediate",
                      onClick: () => {
                        setEditing(row);
                        setFormOpen(true);
                      },
                    },
                    ...(row.enabled
                      ? [
                          {
                            key: "disable",
                            label: t("identityProviders.disable"),
                            hidden: !canEdit?.can,
                            safety: "confirm" as const,
                            onClick: () => void toggleEnabled(row),
                          },
                        ]
                      : [
                          {
                            key: "enable",
                            label: t("identityProviders.enable"),
                            hidden: !canEdit?.can,
                            action: {
                              safety: "immediate" as const,
                              recordName: row.display_name,
                              outcome: t("identityProviders.enable.outcome"),
                              execute: () =>
                                patchIdentityProvider(row.id, { enabled: true }),
                              onSuccess: () => reload(),
                            },
                          },
                        ]),
                    {
                      key: "test",
                      label: t("identityProviders.test"),
                      hidden: !canEdit?.can,
                      disabledReason:
                        testingId === row.id
                          ? t("identityProviders.test")
                          : undefined,
                      safety: "immediate",
                      onClick: () => void runTest(row),
                    },
                    {
                      key: "delete",
                      label: t("actions.delete"),
                      color: "red",
                      hidden: !canDelete?.can,
                      safety: "confirm",
                      onClick: () => void openDelete(row),
                    },
                  ] satisfies RowActionVerb[]}
                />
              </Table.Td>
            ) : null}
          </Table.Tr>
        ))}
      </ListTable>

      <Modal.Stack>
        <SpecDrivenForm
          key={editing?.id ?? "create"}
          opened={formOpen}
          provider={editing}
          onSubmit={save}
          onClose={() => {
            setFormOpen(false);
            setEditing(undefined);
          }}
        />

        <Modal
          stackId="identity-provider-test"
          opened={testResult !== null}
          onClose={() => setTestResult(null)}
          title={t("identityProviders.test")}
          size="md"
        >
          {testResult ? (
            <Stack gap="sm">
              <Text size="sm">
                {t("identityProviders.test.issuer")}: {testResult.issuer}
              </Text>
              <Text size="sm">
                {t("identityProviders.test.groupClaim")}:{" "}
                <Code>{testResult.group_claim}</Code>
              </Text>
              <Text size="sm" c="dimmed">
                {t("identityProviders.test.scopeHint")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("identityProviders.test.noGroupsHint")}
              </Text>
            </Stack>
          ) : null}
        </Modal>

        <ConfirmActionModal
          stackId="identity-provider-disable"
          opened={disableConfirm.opened}
          onClose={disableConfirm.close}
          title={t("identityProviders.disable.confirmTitle")}
          body={
            disableConfirm.pending
              ? t("identityProviders.disable.confirmBody", {
                  count: disableConfirm.pending.bound_user_count,
                })
              : null
          }
          confirmColor="red"
          loading={disabling}
          size="md"
          onConfirm={() => void confirmDisable()}
        >
          <Checkbox
            label={t("identityProviders.disable.disableBound")}
            checked={cascadeOnDisable}
            onChange={(event) =>
              setCascadeOnDisable(event.currentTarget.checked)
            }
          />
          {cascadeOnDisable ? (
            <Text size="sm" c="dimmed">
              {t("identityProviders.disable.skipSelf")}
            </Text>
          ) : null}
        </ConfirmActionModal>

        <ConfirmActionModal
          stackId="identity-provider-delete"
          opened={deleteConfirm.opened}
          onClose={deleteConfirm.close}
          title={t("identityProviders.delete.confirmTitle")}
          body={
            deleteConfirm.pending
              ? t("identityProviders.delete.confirmBody", {
                  count: deleteConfirm.pending.bound_user_count,
                })
              : null
          }
          confirmColor="red"
          loading={deleting}
          size="md"
          onConfirm={() => void confirmDelete()}
        >
          <Checkbox
            label={t("identityProviders.delete.disableBound")}
            checked={disableBoundUsers}
            onChange={(event) =>
              setDisableBoundUsers(event.currentTarget.checked)
            }
          />
          {disableBoundUsers ? (
            <Text size="sm" c="dimmed">
              {t("identityProviders.disable.skipSelf")}
            </Text>
          ) : null}
        </ConfirmActionModal>
      </Modal.Stack>
    </PageChrome>
  );
}
